$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$evaluator = Join-Path $PSScriptRoot 'avaliar-transcricao.ps1'
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('synapse-transcricao-test-' + [guid]::NewGuid().ToString('N'))
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if (-not [IO.Path]::GetFullPath($fixtureRoot).StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Diretorio de teste fora do temporario.' }

function Write-Json($Value, [string]$Path) {
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Expect-Rejection([scriptblock]$Action, [string]$ExpectedMessage) {
    $rejected = $false
    try { & $Action | Out-Null }
    catch {
        if (-not $_.Exception.Message.Contains($ExpectedMessage)) { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw "Deveria rejeitar: $ExpectedMessage" }
}

try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    $source = Join-Path $PSScriptRoot '../src/test/resources/transcricao/corpus.json'
    Copy-Item -LiteralPath $source -Destination (Join-Path $fixtureRoot 'corpus.json')
    $corpus = Get-Content -LiteralPath $source -Raw -Encoding UTF8 | ConvertFrom-Json
    $speakers = @('synthetic-a', 'synthetic-b') | ForEach-Object {
        @{ id = $_; authorized_by = 'TESTE SINTETICO, NAO E VOZ'; authorized_on = '2026-10-05'; consent_reference = 'TESTE DE VALIDACAO'; repository_authorized = $true; external_processing_authorized = $true }
    }
    $recordings = @()
    $counter = 0
    foreach ($speaker in $speakers) {
        foreach ($phrase in $corpus.phrases) {
            $counter++
            $format = @('webm', 'ogg', 'wav', 'mp4')[$counter % 4]
            $file = "synthetic-$counter.$format"
            # Bytes invalidos como audio exercitam apenas o manifesto e as metricas offline.
            [IO.File]::WriteAllBytes((Join-Path $fixtureRoot $file), [byte[]]@($counter))
            $recordings += @{ id = "synthetic-$counter"; speaker_id = $speaker.id; file = $file; sha256 = (Get-FileHash -LiteralPath (Join-Path $fixtureRoot $file)).Hash; format = $format; codec = 'synthetic'; duration_seconds = 12; browser = 'synthetic'; condition = @('quiet', 'office_noise', 'fast')[$counter % 3]; kind = 'speech'; phrase_ids = @($phrase.id); expected_text = $phrase.text }
        }
    }
    foreach ($format in @('webm', 'ogg', 'wav', 'mp4')) {
        foreach ($condition in @('quiet', 'office_noise')) {
            $counter++
            $file = "synthetic-$counter.$format"
            [IO.File]::WriteAllBytes((Join-Path $fixtureRoot $file), [byte[]]@($counter))
            $recordings += @{ id = "synthetic-$counter"; speaker_id = 'synthetic-a'; file = $file; sha256 = (Get-FileHash -LiteralPath (Join-Path $fixtureRoot $file)).Hash; format = $format; codec = 'synthetic'; duration_seconds = 10; browser = 'synthetic'; condition = $condition; kind = 'silence'; phrase_ids = @(); expected_text = '' }
        }
    }
    $counter++
    $file = "synthetic-$counter.webm"
    [IO.File]::WriteAllBytes((Join-Path $fixtureRoot $file), [byte[]]@($counter))
    $recordings += @{ id = "synthetic-$counter"; speaker_id = 'synthetic-a'; file = $file; sha256 = (Get-FileHash -LiteralPath (Join-Path $fixtureRoot $file)).Hash; format = 'webm'; codec = 'synthetic'; duration_seconds = 175; browser = 'synthetic'; condition = 'quiet'; kind = 'long'; phrase_ids = @('r01'); expected_text = $corpus.phrases[0].text }
    $manifestPath = Join-Path $fixtureRoot 'gravacoes.json'
    $manifest = @{ version = 1; speakers = $speakers; recordings = $recordings }
    Write-Json $manifest $manifestPath
    $complete = & $evaluator -Mode gravacoes -FixturesPath $fixtureRoot | ConvertFrom-Json
    if (-not $complete.ready_for_comparison -or @($complete.missing_requirements).Count -ne 0) { throw 'Conjunto completo recebeu pendencias.' }

    $runs = @()
    foreach ($candidateId in @('synthetic-good', 'synthetic-bad')) {
        foreach ($recording in $recordings) {
            foreach ($attempt in 1..3) {
                $annotations = @()
                $index = 0
                foreach ($phraseId in $recording.phrase_ids) {
                    $phrase = $corpus.phrases | Where-Object { $_.id -eq $phraseId }
                    foreach ($element in $phrase.elements) {
                        $annotations += @{ element_id = "${index}:${phraseId}.$($element.id)"; correct = $true; representation = 'words'; evidence = $element.spoken }
                    }
                    $index++
                }
                $run = @{ candidate_id = $candidateId; recording_id = $recording.id; attempt = $attempt; audio_sha256 = $recording.sha256; status = 'ok'; http_status = 200; latency_ms = 100; text = $recording.expected_text; reviewed_by = 'synthetic-test'; unexpected_elements = 0; annotations = $annotations }
                if ($candidateId -eq 'synthetic-bad') {
                    if ($recording.kind -eq 'silence') { $run.text = 'texto inventado'; $run.unexpected_elements = 1 }
                    else { $run.status = 'error'; $run.http_status = 0; $run.text = ''; $run.annotations = @() }
                }
                $runs += $run
            }
        }
    }
    $results = @{ version = 1; candidates = @(
        @{ id = 'synthetic-good'; provider = 'synthetic-provider-a'; model = 'synthetic'; endpoint = 'https://example.invalid'; language = 'pt-BR'; settings = @{}; usd_per_minute = 0.01 },
        @{ id = 'synthetic-bad'; provider = 'synthetic-provider-b'; model = 'synthetic'; endpoint = 'https://example.invalid'; language = 'pt-BR'; settings = @{}; usd_per_minute = 0.01 }
    ); runs = $runs }
    $resultsPath = Join-Path $fixtureRoot 'results.json'
    Write-Json $results $resultsPath
    $summary = & $evaluator -Mode resultados -FixturesPath $fixtureRoot -ResultsPath $resultsPath | ConvertFrom-Json
    $good = $summary.candidates | Where-Object { $_.candidate -eq 'synthetic-good' }
    $bad = $summary.candidates | Where-Object { $_.candidate -eq 'synthetic-bad' }
    if ($good.accuracy.percentual.rate -ne 1 -or $good.wer -ne 0 -or $good.silence_with_text -ne 0) { throw 'Falha no caso sem erros.' }
    if ($bad.accuracy.percentual.rate -ne 0 -or $bad.wer -ne 1 -or $bad.silence_with_text -ne 24 -or $bad.errors -ne 75) { throw 'Falha no denominador ou controle de silencio.' }

    $partialRecordings = @($recordings | Where-Object { $_.kind -eq 'speech' } | ForEach-Object {
        $partial = $_.Clone()
        $partial.file = "partial-$($partial.id).ogg"
        Copy-Item -LiteralPath (Join-Path $fixtureRoot $_.file) -Destination (Join-Path $fixtureRoot $partial.file)
        $partial.format = 'ogg'
        $partial
    })
    $manifest.recordings = $partialRecordings
    Write-Json $manifest $manifestPath
    $partialSummary = & $evaluator -Mode gravacoes -FixturesPath $fixtureRoot | ConvertFrom-Json
    if ($partialSummary.status -ne 'gravacoes_incompletas' -or
        $partialSummary.ready_for_comparison -or
        $partialSummary.recordings -ne 24 -or
        @($partialSummary.missing_requirements).Count -ne 12 -or
        $partialSummary.missing_requirements -notcontains 'Fala sem formato: webm') {
        throw 'Conjunto parcial nao informou todas as pendencias.'
    }
    Expect-Rejection { & $evaluator -Mode resultados -FixturesPath $fixtureRoot -ResultsPath $resultsPath } 'Conjunto de gravacoes incompleto'
    $manifest.recordings = $recordings
    Write-Json $manifest $manifestPath

    $results.runs = @($runs[0])
    Write-Json $results $resultsPath
    Expect-Rejection { & $evaluator -Mode resultados -FixturesPath $fixtureRoot -ResultsPath $resultsPath } 'Matriz incompleta'
    $results.runs = @($runs[0], $runs[0])
    Write-Json $results $resultsPath
    Expect-Rejection { & $evaluator -Mode resultados -FixturesPath $fixtureRoot -ResultsPath $resultsPath } 'Resultado duplicado'
    $manifest.excluded_phrase_ids = @('r09')
    Write-Json $manifest $manifestPath
    $filtered = & $evaluator -Mode gravacoes -FixturesPath $fixtureRoot | ConvertFrom-Json
    if ($filtered.recordings -ne 31) { throw 'Frase excluida permaneceu na comparacao.' }
    $manifest.excluded_phrase_ids = @('r09', 'r10', 'r11')
    Write-Json $manifest $manifestPath
    Expect-Rejection { & $evaluator -Mode gravacoes -FixturesPath $fixtureRoot } 'ao menos dez frases'
    $manifest.excluded_phrase_ids = @()
    $manifest.speakers[0].external_processing_authorized = $false
    Write-Json $manifest $manifestPath
    Expect-Rejection { & $evaluator -Mode gravacoes -FixturesPath $fixtureRoot } 'Uso da voz nao autorizado'
    $manifest.speakers[0].external_processing_authorized = $true
    $manifest.recordings[0].sha256 = '0' * 64
    Write-Json $manifest $manifestPath
    Expect-Rejection { & $evaluator -Mode gravacoes -FixturesPath $fixtureRoot } 'Hash de audio divergente'
    @{ status = 'ok'; tests = 11; data = 'synthetic_only'; providers_called = $false } | ConvertTo-Json
} finally {
    $resolvedTarget = [IO.Path]::GetFullPath($fixtureRoot)
    if ($resolvedTarget.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolvedTarget -Leaf).StartsWith('synapse-transcricao-test-')) {
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    }
}
