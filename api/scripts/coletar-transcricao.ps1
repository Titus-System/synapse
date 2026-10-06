param(
    [ValidateSet('planejar', 'coletar')]
    [string]$Mode = 'planejar',
    [string]$FixturesPath = (Join-Path $PSScriptRoot '../src/test/resources/transcricao'),
    [string]$ResultsPath,
    [ValidateSet('openai', 'groq')]
    [string]$SecondProvider = 'openai',
    [ValidateSet('eu', 'us')]
    [string]$DeepgramRegion = 'eu',
    [ValidateRange(0, 10)]
    [double]$DeepgramUsdPerMinute = 0.0043,
    [ValidateRange(0, 10)]
    [double]$OpenAIUsdPerMinute = 0.006,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Net.Http

function New-TranscriptionRequest($Candidate, [string]$File, [string]$Format, [string]$ApiKey) {
    $contentTypes = @{ webm = 'audio/webm'; ogg = 'audio/ogg'; wav = 'audio/wav'; mp4 = 'audio/mp4' }
    $audio = New-Object System.Net.Http.ByteArrayContent -ArgumentList (,[IO.File]::ReadAllBytes($File))
    $audio.Headers.ContentType = New-Object System.Net.Http.Headers.MediaTypeHeaderValue $contentTypes[$Format]
    $uri = $Candidate.endpoint
    if ($Candidate.provider -eq 'deepgram') {
        $uri += '?model=nova-3&language=pt-BR&smart_format=false&mip_opt_out=true'
    }
    $request = New-Object System.Net.Http.HttpRequestMessage ([System.Net.Http.HttpMethod]::Post), $uri
    if ($Candidate.provider -eq 'deepgram') {
        $request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue 'Token', $ApiKey
        $request.Content = $audio
    } else {
        $request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue 'Bearer', $ApiKey
        $multipart = New-Object System.Net.Http.MultipartFormDataContent
        $multipart.Add($audio, 'file', [IO.Path]::GetFileName($File))
        foreach ($field in @{ model = $Candidate.model; language = 'pt'; response_format = 'json' }.GetEnumerator()) {
            $multipart.Add((New-Object System.Net.Http.StringContent $field.Value), $field.Key)
        }
        $request.Content = $multipart
    }
    return $request
}

function Invoke-TranscriptionAttempt([System.Net.Http.HttpClient]$Client, $Candidate, $Recording, [string]$File, [string]$ApiKey, [int]$Attempt) {
    $run = [ordered]@{
        candidate_id = $Candidate.id
        recording_id = $Recording.id
        attempt = $Attempt
        audio_sha256 = $Recording.sha256
        started_at_utc = [DateTime]::UtcNow.ToString('o')
        status = 'error'
        http_status = 0
        latency_ms = 0
        text = ''
        failure_reason = ''
        request_id = ''
        reviewed_by = ''
        unexpected_elements = $null
        annotations = @()
    }
    $request = New-TranscriptionRequest $Candidate $File $Recording.format $ApiKey
    $response = $null
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        $response = $Client.SendAsync($request).GetAwaiter().GetResult()
        $run.http_status = [int]$response.StatusCode
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if ($response.Headers.Contains('x-request-id')) {
            $requestId = @($response.Headers.GetValues('x-request-id'))[0]
            if ($requestId -cmatch '^[a-zA-Z0-9_-]{1,128}$') { $run.request_id = $requestId }
        }
        if (-not $response.IsSuccessStatusCode) {
            if ($run.http_status -eq 415) { $run.status = 'unsupported' }
            $run.failure_reason = 'http_error'
        } else {
            try {
                $decoded = $body | ConvertFrom-Json
                if ($Candidate.provider -eq 'deepgram') {
                    $text = $decoded.results.channels[0].alternatives[0].transcript
                    if ($decoded.PSObject.Properties['metadata'] -and $decoded.metadata.PSObject.Properties['request_id']) {
                        $requestId = $decoded.metadata.request_id
                        if ($requestId -is [string] -and $requestId -cmatch '^[a-zA-Z0-9_-]{1,128}$') { $run.request_id = $requestId }
                    }
                } else { $text = $decoded.text }
                if ($text -isnot [string]) { throw 'Campo de transcricao invalido.' }
                $run.text = $text
                $run.status = 'ok'
            } catch { $run.failure_reason = 'invalid_response' }
        }
    } catch {
        $reason = 'transport_error'
        $exception = $_.Exception
        while ($null -ne $exception) {
            if ($exception -is [OperationCanceledException]) { $reason = 'timeout'; break }
            $exception = $exception.InnerException
        }
        $run.failure_reason = $reason
    } finally {
        $clock.Stop()
        $run.latency_ms = [Math]::Max(1, [Math]::Round($clock.Elapsed.TotalMilliseconds, 3))
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose()
    }
    return $run
}

function Save-TranscriptionRound($Round, [string]$Path) {
    $encoding = New-Object Text.UTF8Encoding $false
    $json = $Round | ConvertTo-Json -Depth 15
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = $encoding.GetBytes($json + [Environment]::NewLine)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
    } finally { $stream.Dispose() }
}

if ($MyInvocation.InvocationName -eq '.') { return }

$evaluator = Join-Path $PSScriptRoot 'avaliar-transcricao.ps1'
$validation = & $evaluator -Mode gravacoes -FixturesPath $FixturesPath | ConvertFrom-Json
$manifestFile = Join-Path $FixturesPath 'gravacoes.json'
$corpusFile = Join-Path $FixturesPath 'corpus.json'
$manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
$corpus = Get-Content -LiteralPath $corpusFile -Raw -Encoding UTF8 | ConvertFrom-Json
$excluded = @()
if ($manifest.PSObject.Properties['excluded_phrase_ids']) { $excluded = @($manifest.excluded_phrase_ids) }
$recordings = @($manifest.recordings | Where-Object { @($_.phrase_ids | Where-Object { $_ -in $excluded }).Count -eq 0 } | Sort-Object id)
$deepgramEndpoint = 'https://api.eu.deepgram.com/v1/listen'
if ($DeepgramRegion -eq 'us') { $deepgramEndpoint = 'https://api.deepgram.com/v1/listen' }
$candidates = @(
    [pscustomobject]@{ id = 'deepgram-nova3'; provider = 'deepgram'; model = 'nova-3'; endpoint = $deepgramEndpoint; language = 'pt-BR'; settings = @{ language = 'pt-BR'; smart_format = $false; mip_opt_out = $true }; usd_per_minute = $DeepgramUsdPerMinute },
    [pscustomobject]@{ id = 'openai-4o-transcribe'; provider = 'openai'; model = 'gpt-4o-transcribe'; endpoint = 'https://api.openai.com/v1/audio/transcriptions'; language = 'pt-BR'; settings = @{ language = 'pt'; response_format = 'json'; brazilian_variant_selector = $false }; usd_per_minute = $OpenAIUsdPerMinute }
)
if ($SecondProvider -eq 'groq') {
    $candidates[1] = [pscustomobject]@{
        id = 'groq-whisper-large-v3'; provider = 'groq'; model = 'whisper-large-v3'
        endpoint = 'https://api.groq.com/openai/v1/audio/transcriptions'
        language = 'pt-BR'
        settings = @{ language = 'pt'; response_format = 'json'; temperature_default = 0; prompt_omitted = $true }
        usd_per_minute = 0.111 / 60
    }
}
$secrets = @{}
$missingKeys = @()
$secondKey = 'OPENAI_API_KEY'
if ($SecondProvider -eq 'groq') { $secondKey = 'GROQ_API_KEY' }
foreach ($name in @('DEEPGRAM_API_KEY', $secondKey)) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) { $missingKeys += $name }
    else { $secrets[$name] = $value }
}
$uncheckedReadings = @($recordings | Where-Object { -not $_.PSObject.Properties['reading_verified'] -or $_.reading_verified -ne $true }).Count
$minutesPerCandidate = (($recordings | Measure-Object -Property duration_seconds -Sum).Sum / 60) * 3
$nominalCost = 0.0
foreach ($candidate in $candidates) {
    $billableMinutes = $minutesPerCandidate
    if ($candidate.provider -eq 'groq') {
        $billableSeconds = ($recordings | ForEach-Object { [Math]::Max(10, $_.duration_seconds) } | Measure-Object -Sum).Sum
        $billableMinutes = ($billableSeconds / 60) * 3
    }
    $nominalCost += $billableMinutes * $candidate.usd_per_minute
}
$plan = @{
    status = 'planejado_sem_chamadas'
    providers_called = $false
    recordings = $recordings.Count
    attempts_per_file_per_candidate = 3
    planned_requests = $recordings.Count * 3 * $candidates.Count
    ready_for_collection = ($validation.ready_for_comparison -and $uncheckedReadings -eq 0 -and $missingKeys.Count -eq 0)
    missing_requirements = @($validation.missing_requirements)
    readings_pending_review = $uncheckedReadings
    missing_environment_variables = $missingKeys
    candidates = $candidates
    estimated_usd_nominal = [Math]::Round($nominalCost, 6)
    cost_basis = 'tarifas documentais configuraveis; confirmar conta, opt-out, creditos e arredondamento antes de coletar'
}
if ($Mode -eq 'planejar') { $plan | ConvertTo-Json -Depth 8; return }
if (-not $validation.ready_for_comparison) { throw ('Conjunto de gravacoes incompleto: ' + ($validation.missing_requirements -join '; ')) }
if ($uncheckedReadings -gt 0) { throw 'Confira as leituras reais e preencha reading_verified=true antes do envio.' }
if ($missingKeys.Count -gt 0) { throw ('Variaveis ausentes no processo: ' + ($missingKeys -join ', ')) }
if ([string]::IsNullOrWhiteSpace($ResultsPath)) { throw 'Informe ResultsPath para salvar a rodada real.' }
$outputFile = [IO.Path]::GetFullPath($ResultsPath)
if (Test-Path -LiteralPath $outputFile) { throw 'ResultsPath ja existe. Use outro arquivo para preservar a rodada anterior.' }
if (-not (Test-Path -LiteralPath (Split-Path $outputFile -Parent) -PathType Container)) { throw 'O diretorio de ResultsPath deve existir.' }
$round = [ordered]@{
    version = 1
    status = 'coleta_em_andamento'
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    fixtures_manifest_sha256 = (Get-FileHash -LiteralPath $manifestFile -Algorithm SHA256).Hash.ToLowerInvariant()
    corpus_sha256 = (Get-FileHash -LiteralPath $corpusFile -Algorithm SHA256).Hash.ToLowerInvariant()
    candidates = $candidates
    runs = @()
}
Save-TranscriptionRound $round $outputFile
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect = $false
$client = New-Object System.Net.Http.HttpClient $handler
$client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
try {
    foreach ($attempt in 1..3) {
        foreach ($recording in $recordings) {
            $order = @(0, 1)
            if ($attempt -eq 2) { $order = @(1, 0) }
            foreach ($position in $order) {
                $candidate = $candidates[$position]
                $file = [IO.Path]::GetFullPath((Join-Path $FixturesPath $recording.file))
                if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $recording.sha256) { throw 'Audio mudou durante a rodada.' }
                $keyName = 'DEEPGRAM_API_KEY'
                if ($candidate.provider -eq 'openai') { $keyName = 'OPENAI_API_KEY' }
                if ($candidate.provider -eq 'groq') { $keyName = 'GROQ_API_KEY' }
                $run = Invoke-TranscriptionAttempt $client $candidate $recording $file $secrets[$keyName] $attempt
                if ($run.status -eq 'ok') {
                    $index = 0
                    foreach ($phraseId in $recording.phrase_ids) {
                        $phrase = $corpus.phrases | Where-Object { $_.id -eq $phraseId }
                        foreach ($element in $phrase.elements) {
                            $run.annotations += @{ element_id = "${index}:${phraseId}.$($element.id)"; correct = $null; representation = ''; evidence = '' }
                        }
                        $index++
                    }
                }
                $round.runs += $run
                Save-TranscriptionRound $round $outputFile
                Write-Progress -Activity 'Coletando transcricoes' -Status "$($candidate.id): $($recording.id), tentativa $attempt" -PercentComplete (100 * $round.runs.Count / $plan.planned_requests)
                if ($run.http_status -in @(401, 403, 429)) { throw 'Conta recusou a rodada (autorizacao, quota ou limite). Confira o painel antes de iniciar outra rodada.' }
            }
        }
    }
    $round.status = 'aguardando_revisao_humana'
    Save-TranscriptionRound $round $outputFile
    @{ status = $round.status; providers_called = $true; runs = $round.runs.Count; results_path = $outputFile } | ConvertTo-Json
} finally {
    Write-Progress -Activity 'Coletando transcricoes' -Completed
    $client.Dispose()
    $secrets.Clear()
}
