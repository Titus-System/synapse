param(
    [ValidateSet('corpus', 'gravacoes', 'resultados', 'autoteste')]
    [string]$Mode = 'corpus',
    [string]$FixturesPath = (Join-Path $PSScriptRoot '../src/test/resources/transcricao'),
    [string]$ResultsPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Valid([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Read-Json([string]$Path) {
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Nao foi possivel ler o JSON: $Path" }
}

function Assert-Fields($Value, [string[]]$Fields) {
    foreach ($field in $Fields) {
        Assert-Valid ($null -ne $Value.PSObject.Properties[$field]) "Campo obrigatorio ausente: $field"
    }
}

function Get-Tokens([string]$Text) {
    return @([regex]::Matches($Text.ToLowerInvariant(), '[\p{L}\p{N}]+') | ForEach-Object { $_.Value })
}

function Get-WordErrors([string]$Expected, [string]$Actual) {
    $reference = @(Get-Tokens $Expected)
    $hypothesis = @(Get-Tokens $Actual)
    $previous = [int[]](0..$hypothesis.Count)
    for ($i = 1; $i -le $reference.Count; $i++) {
        $current = New-Object 'int[]' ($hypothesis.Count + 1)
        $current[0] = $i
        for ($j = 1; $j -le $hypothesis.Count; $j++) {
            $substitution = [int]($reference[$i - 1] -cne $hypothesis[$j - 1])
            $current[$j] = [Math]::Min([Math]::Min($current[$j - 1] + 1, $previous[$j] + 1), $previous[$j - 1] + $substitution)
        }
        $previous = $current
    }
    return @{ errors = $previous[$hypothesis.Count]; words = $reference.Count }
}

function Get-Percentile([double[]]$Values, [double]$Percentile) {
    $sorted = @($Values | Sort-Object)
    return $sorted[[Math]::Max(0, [int][Math]::Ceiling($sorted.Count * $Percentile) - 1)]
}

function Get-LocalFile([string]$RelativePath) {
    Assert-Valid (-not [IO.Path]::IsPathRooted($RelativePath)) 'O caminho deve ser relativo as fixtures.'
    $root = [IO.Path]::GetFullPath($FixturesPath).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $target = [IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    Assert-Valid ($target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) 'Arquivo fora das fixtures.'
    Assert-Valid (Test-Path -LiteralPath $target -PathType Leaf) "Arquivo ausente: $RelativePath"
    return $target
}

if ($Mode -eq 'autoteste') {
    $cases = @(
        @('dois por cento', 'dois por cento', 0, 3),
        @('dois por cento', 'tres por cento', 1, 3),
        @('dois por cento', 'dois cento', 1, 3),
        @('dois por cento', 'dois por cento hoje', 1, 3),
        @('dois por cento', '', 3, 3),
        @('', 'texto inventado', 2, 0),
        @('', '', 0, 0),
        @('COMISSAO: dois!', 'comissao dois', 0, 2)
    )
    foreach ($case in $cases) {
        $result = Get-WordErrors $case[0] $case[1]
        Assert-Valid ($result.errors -eq $case[2] -and $result.words -eq $case[3]) 'Falha no autoteste de WER.'
    }
    Assert-Valid ((Get-Percentile @(10, 20, 30) 0.95) -eq 30) 'Falha no percentil.'
    @{ status = 'ok'; tests = 9 } | ConvertTo-Json
    return
}

$corpus = Read-Json (Join-Path $FixturesPath 'corpus.json')
Assert-Fields $corpus @('version', 'language', 'phrases')
Assert-Valid ($corpus.version -eq 1 -and $corpus.language -ceq 'pt-BR') 'Versao ou idioma invalido.'
Assert-Valid (@($corpus.phrases).Count -ge 10) 'Sao necessarias ao menos dez frases.'
$phrases = @{}
$types = @('percentual', 'monetario', 'data', 'loja', 'marca', 'cargo', 'matricula', 'exclusao')
$coverage = @{}
foreach ($type in $types) { $coverage[$type] = 0 }
foreach ($phrase in $corpus.phrases) {
    Assert-Fields $phrase @('id', 'source', 'text', 'elements')
    Assert-Valid ($phrase.id -cmatch '^r[0-9]{2}$' -and -not $phrases.ContainsKey($phrase.id)) 'ID de frase invalido ou duplicado.'
    Assert-Valid (-not [string]::IsNullOrWhiteSpace($phrase.text) -and -not [string]::IsNullOrWhiteSpace($phrase.source)) 'Frase sem texto ou origem.'
    Assert-Valid (@($phrase.elements).Count -gt 0) 'Frase sem elementos.'
    $ids = @{}
    foreach ($element in $phrase.elements) {
        Assert-Fields $element @('id', 'type', 'value', 'spoken')
        Assert-Valid ($types -ccontains $element.type) 'Tipo de elemento invalido.'
        Assert-Valid (-not $ids.ContainsKey($element.id) -and -not [string]::IsNullOrWhiteSpace($element.id)) 'Elemento sem ID ou duplicado.'
        Assert-Valid (-not [string]::IsNullOrWhiteSpace($element.value)) 'Elemento sem valor esperado.'
        Assert-Valid (-not [string]::IsNullOrWhiteSpace($element.spoken) -and $phrase.text.Contains($element.spoken)) 'Trecho esperado ausente da frase.'
        if ($element.type -eq 'matricula') {
            Assert-Valid ($element.value -cmatch '^MATRIC-90000[1-4]$') 'Use apenas as matriculas ficticias reservadas no corpus.'
        }
        $ids[$element.id] = $true
        $coverage[$element.type]++
    }
    $phrases[$phrase.id] = $phrase
}
foreach ($type in $types) { Assert-Valid ($coverage[$type] -gt 0) "Cobertura ausente: $type" }
if ($Mode -eq 'corpus') {
    @{ status = 'corpus_validado'; phrases = $phrases.Count; elements = $coverage; audio_evaluated = $false } | ConvertTo-Json -Depth 5
    return
}

$manifest = Read-Json (Join-Path $FixturesPath 'gravacoes.json')
Assert-Fields $manifest @('version', 'speakers', 'recordings')
Assert-Valid ($manifest.version -eq 1) 'Versao do manifesto invalida.'
$excludedPhraseIds = @()
if ($manifest.PSObject.Properties['excluded_phrase_ids']) {
    $excludedPhraseIds = @($manifest.excluded_phrase_ids)
    foreach ($phraseId in $excludedPhraseIds) { Assert-Valid ($phrases.ContainsKey($phraseId)) 'Exclusao de frase desconhecida.' }
}
$activePhrases = @($corpus.phrases | Where-Object { $_.id -notin $excludedPhraseIds })
Assert-Valid ($activePhrases.Count -ge 10) 'A comparacao deve manter ao menos dez frases.'
$activeRecordings = @($manifest.recordings | Where-Object { @($_.phrase_ids | Where-Object { $_ -in $excludedPhraseIds }).Count -eq 0 })
Assert-Valid (@($manifest.speakers).Count -ge 2 -and @($manifest.recordings).Count -gt 0) 'Gravacoes e autorizacoes de pelo menos duas pessoas ainda nao foram fornecidas.'
$speakers = @{}
foreach ($speaker in $manifest.speakers) {
    Assert-Fields $speaker @('id', 'authorized_by', 'authorized_on', 'consent_reference', 'repository_authorized', 'external_processing_authorized')
    Assert-Valid (-not $speakers.ContainsKey($speaker.id) -and -not [string]::IsNullOrWhiteSpace($speaker.id)) 'ID de voz ausente ou duplicado.'
    Assert-Valid (-not [string]::IsNullOrWhiteSpace($speaker.authorized_by) -and -not [string]::IsNullOrWhiteSpace($speaker.consent_reference)) 'Autorizacao de voz sem responsavel ou referencia.'
    Assert-Valid ($speaker.authorized_on -match '^\d{4}-\d{2}-\d{2}$') 'Data de autorizacao invalida.'
    Assert-Valid ($speaker.repository_authorized -is [bool] -and $speaker.repository_authorized -and $speaker.external_processing_authorized -is [bool] -and $speaker.external_processing_authorized) 'Uso da voz nao autorizado.'
    $speakers[$speaker.id] = $speaker
}
$recordings = @{}
$expectedElements = @{}
$bytes = 0L
foreach ($recording in $activeRecordings) {
    Assert-Fields $recording @('id', 'speaker_id', 'file', 'sha256', 'format', 'codec', 'duration_seconds', 'browser', 'condition', 'kind', 'phrase_ids', 'expected_text')
    Assert-Valid (-not $recordings.ContainsKey($recording.id) -and $recording.id -cmatch '^[a-z0-9_-]+$') 'ID de gravacao invalido ou duplicado.'
    Assert-Valid ($speakers.ContainsKey($recording.speaker_id)) 'Voz sem autorizacao.'
    Assert-Valid (@('webm', 'ogg', 'wav', 'mp4') -ccontains $recording.format) 'Formato fora da T-230.'
    Assert-Valid (@('quiet', 'office_noise', 'fast') -ccontains $recording.condition) 'Condicao invalida.'
    Assert-Valid (@('speech', 'silence', 'long') -ccontains $recording.kind) 'Tipo de gravacao invalido.'
    Assert-Valid (-not [string]::IsNullOrWhiteSpace($recording.codec) -and -not [string]::IsNullOrWhiteSpace($recording.browser)) 'Codec ou navegador ausente.'
    Assert-Valid ($recording.duration_seconds -gt 0 -and $recording.duration_seconds -le 180) 'Duracao fora de 0 a 180 segundos.'
    $file = Get-LocalFile $recording.file
    $size = (Get-Item -LiteralPath $file).Length
    Assert-Valid ($size -gt 0 -and $size -le 5000000) 'Arquivo vazio ou acima de 5 MB.'
    Assert-Valid ($recording.sha256 -match '^[a-fA-F0-9]{64}$' -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -eq $recording.sha256) 'Hash de audio divergente.'
    $bytes += $size
    $texts = @()
    $elements = @{}
    $index = 0
    foreach ($phraseId in $recording.phrase_ids) {
        Assert-Valid ($phrases.ContainsKey($phraseId)) 'Gravacao aponta para frase inexistente.'
        $texts += $phrases[$phraseId].text
        foreach ($element in $phrases[$phraseId].elements) { $elements["${index}:${phraseId}.$($element.id)"] = $element }
        $index++
    }
    Assert-Valid ($recording.expected_text -ceq ($texts -join ' ')) 'Texto esperado difere da sequencia de frases.'
    if ($recording.kind -eq 'silence') {
        Assert-Valid (@($recording.phrase_ids).Count -eq 0 -and $recording.expected_text -ceq '') 'Controle de silencio deve ter texto vazio.'
    } else { Assert-Valid ($elements.Count -gt 0) 'Gravacao de fala sem frases.' }
    if ($recording.kind -eq 'long') { Assert-Valid ($recording.duration_seconds -ge 165) 'Controle longo deve durar de 165 a 180 segundos.' }
    $recordings[$recording.id] = $recording
    $expectedElements[$recording.id] = $elements
}
Assert-Valid ($bytes -le 20000000) 'Fixtures acima do orcamento de 20 MB.'
foreach ($phraseId in $activePhrases.id) {
    $voices = @($activeRecordings | Where-Object { $_.kind -eq 'speech' -and $_.phrase_ids -contains $phraseId } | Select-Object -ExpandProperty speaker_id -Unique)
    Assert-Valid ($voices.Count -ge 2) "Frase sem duas vozes: $phraseId"
}
$missingRequirements = @()
foreach ($format in @('webm', 'ogg', 'wav', 'mp4')) {
    if (@($activeRecordings | Where-Object { $_.format -eq $format -and $_.kind -eq 'speech' }).Count -eq 0) {
        $missingRequirements += "Fala sem formato: $format"
    }
    foreach ($condition in @('quiet', 'office_noise')) {
        if (@($activeRecordings | Where-Object { $_.format -eq $format -and $_.kind -eq 'silence' -and $_.condition -eq $condition }).Count -eq 0) {
            $missingRequirements += "Silencio ausente: $format/$condition"
        }
    }
}
foreach ($condition in @('office_noise', 'fast')) {
    if (@($activeRecordings | Where-Object { $_.kind -eq 'speech' -and $_.condition -eq $condition }).Count -eq 0) {
        $missingRequirements += "Fala sem condicao: $condition"
    }
}
if (@($activeRecordings | Where-Object { $_.kind -eq 'long' }).Count -eq 0) {
    $missingRequirements += 'Controle de ate tres minutos ausente.'
}
if ($Mode -eq 'gravacoes') {
    $status = 'gravacoes_validadas'
    if ($missingRequirements.Count -gt 0) { $status = 'gravacoes_incompletas' }
    @{
        status = $status
        recordings = $recordings.Count
        bytes = $bytes
        ready_for_comparison = ($missingRequirements.Count -eq 0)
        missing_requirements = $missingRequirements
    } | ConvertTo-Json -Depth 5
    return
}
Assert-Valid ($missingRequirements.Count -eq 0) ('Conjunto de gravacoes incompleto: ' + ($missingRequirements -join '; '))

Assert-Valid (-not [string]::IsNullOrWhiteSpace($ResultsPath)) 'Informe ResultsPath.'
$results = Read-Json $ResultsPath
Assert-Fields $results @('version', 'candidates', 'runs')
Assert-Valid ($results.version -eq 1) 'Versao de resultados invalida.'
Assert-Valid (@($results.candidates).Count -ge 2) 'Avalie ao menos dois candidatos.'
$candidates = @{}
foreach ($candidate in $results.candidates) {
    Assert-Fields $candidate @('id', 'provider', 'model', 'endpoint', 'language', 'settings', 'usd_per_minute')
    Assert-Valid ($candidate.id -cmatch '^[a-z0-9_-]+$' -and -not $candidates.ContainsKey($candidate.id)) 'Candidato invalido ou duplicado.'
    Assert-Valid ($candidate.language -ceq 'pt-BR' -and $candidate.usd_per_minute -ge 0) 'Idioma ou preco invalido.'
    $candidates[$candidate.id] = $candidate
}
Assert-Valid (@($results.candidates | Select-Object -ExpandProperty provider -Unique).Count -ge 2) 'Dois modelos do mesmo provedor nao satisfazem a comparacao.'
$seen = @{}
$observations = @()
foreach ($run in $results.runs) {
    Assert-Fields $run @('candidate_id', 'recording_id', 'attempt', 'audio_sha256', 'status', 'http_status', 'latency_ms', 'text', 'reviewed_by', 'annotations', 'unexpected_elements')
    Assert-Valid ($candidates.ContainsKey($run.candidate_id) -and $recordings.ContainsKey($run.recording_id)) 'Resultado de candidato ou audio desconhecido.'
    Assert-Valid ($run.attempt -in @(1, 2, 3)) 'Tentativa deve ser 1, 2 ou 3.'
    $key = "$($run.candidate_id)/$($run.recording_id)/$($run.attempt)"
    Assert-Valid (-not $seen.ContainsKey($key)) 'Resultado duplicado.'
    $seen[$key] = $true
    $recording = $recordings[$run.recording_id]
    Assert-Valid ($run.audio_sha256 -eq $recording.sha256) 'Candidatos nao receberam o mesmo arquivo.'
    Assert-Valid ($run.status -cin @('ok', 'error', 'unsupported') -and $run.latency_ms -gt 0) 'Status ou latencia invalida.'
    Assert-Valid ($run.http_status -ge 0 -and $run.http_status -le 599) 'Status HTTP invalido.'
    Assert-Valid ($run.unexpected_elements -is [int] -and $run.unexpected_elements -ge 0) 'Contagem de elementos inventados invalida.'
    $annotations = @{}
    if ($run.status -eq 'ok') {
        Assert-Valid ($run.http_status -ge 200 -and $run.http_status -lt 300 -and $run.text -is [string]) 'Resposta de sucesso invalida.'
        Assert-Valid (-not [string]::IsNullOrWhiteSpace($run.reviewed_by)) 'Resultado sem revisor.'
        foreach ($annotation in $run.annotations) {
            Assert-Fields $annotation @('element_id', 'correct', 'representation', 'evidence')
            Assert-Valid ($expectedElements[$run.recording_id].ContainsKey($annotation.element_id) -and -not $annotations.ContainsKey($annotation.element_id)) 'Anotacao desconhecida ou duplicada.'
            Assert-Valid ($annotation.correct -is [bool] -and $annotation.representation -cin @('digits', 'words', 'mixed', 'absent')) 'Anotacao invalida.'
            if ($annotation.correct) {
                Assert-Valid ($annotation.representation -ne 'absent' -and -not [string]::IsNullOrWhiteSpace($annotation.evidence) -and $run.text.Contains($annotation.evidence)) 'Acerto sem trecho de evidencia na transcricao.'
            }
            $annotations[$annotation.element_id] = $annotation
        }
        Assert-Valid ($annotations.Count -eq $expectedElements[$run.recording_id].Count) 'Resultado sem anotacao de todos os elementos.'
    } else {
        Assert-Valid (@($run.annotations).Count -eq 0 -and [string]::IsNullOrEmpty($run.text)) 'Falha nao deve conter transcricao nem acertos.'
    }
    foreach ($id in $expectedElements[$run.recording_id].Keys) {
        $correct = $run.status -eq 'ok' -and $annotations[$id].correct
        $representation = 'absent'
        if ($run.status -eq 'ok') { $representation = $annotations[$id].representation }
        $observations += [pscustomobject]@{ candidate = $run.candidate_id; type = $expectedElements[$run.recording_id][$id].type; correct = $correct; representation = $representation }
    }
}
foreach ($candidateId in $candidates.Keys) {
    foreach ($recordingId in $recordings.Keys) {
        foreach ($attempt in 1..3) { Assert-Valid ($seen.ContainsKey("$candidateId/$recordingId/$attempt")) 'Matriz incompleta: faltam tentativas, incluindo falhas e formatos recusados.' }
    }
}
$summaries = @()
foreach ($candidateId in ($candidates.Keys | Sort-Object)) {
    $runs = @($results.runs | Where-Object { $_.candidate_id -eq $candidateId })
    $accuracy = @{}
    foreach ($type in $types) {
        $items = @($observations | Where-Object { $_.candidate -eq $candidateId -and $_.type -eq $type })
        $correct = @($items | Where-Object { $_.correct }).Count
        $accuracy[$type] = @{ correct = $correct; total = $items.Count; rate = $correct / $items.Count }
    }
    $errors = 0; $words = 0
    foreach ($run in $runs) {
        $wer = Get-WordErrors $recordings[$run.recording_id].expected_text $run.text
        if ($wer.words -gt 0) { $errors += $wer.errors; $words += $wer.words }
    }
    $silence = @($runs | Where-Object { $recordings[$_.recording_id].kind -eq 'silence' -and $_.status -eq 'ok' })
    $long = @($runs | Where-Object { $recordings[$_.recording_id].kind -eq 'long' })
    $formats = @{}
    foreach ($format in @('webm', 'ogg', 'wav', 'mp4')) {
        $items = @($runs | Where-Object { $recordings[$_.recording_id].format -eq $format })
        $formats[$format] = @{ ok = @($items | Where-Object { $_.status -eq 'ok' }).Count; total = $items.Count }
    }
    $minutes = ($runs | ForEach-Object { $recordings[$_.recording_id].duration_seconds / 60 } | Measure-Object -Sum).Sum
    $summaries += @{
        candidate = $candidateId; accuracy = $accuracy; wer = $errors / $words
        errors = @($runs | Where-Object { $_.status -ne 'ok' }).Count
        unexpected_elements = ($runs | Measure-Object -Property unexpected_elements -Sum).Sum
        latency_ms = @{ median_nearest_rank = Get-Percentile @($runs.latency_ms) 0.5; p95 = Get-Percentile @($runs.latency_ms) 0.95; long_p95 = Get-Percentile @($long.latency_ms) 0.95 }
        formats = $formats; silence_successes = $silence.Count
        silence_with_text = @($silence | Where-Object { -not [string]::IsNullOrWhiteSpace($_.text) }).Count
        representations = @($observations | Where-Object { $_.candidate -eq $candidateId } | Group-Object representation | Select-Object Name,Count)
        estimated_usd_nominal = [Math]::Round($minutes * $candidates[$candidateId].usd_per_minute, 6)
    }
}
@{ status = 'avaliacao_completa'; candidates = $summaries; cost_basis = 'todas as tentativas, sem creditos, impostos ou arredondamento do provedor' } | ConvertTo-Json -Depth 8
