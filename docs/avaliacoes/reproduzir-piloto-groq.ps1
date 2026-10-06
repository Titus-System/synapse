$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Set-Location $root
. ./api/scripts/coletar-transcricao.ps1
$manifestPath='api/src/test/resources/transcricao/gravacoes.json'
$manifest=Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$active=@($manifest.recordings | Where-Object { $_.format -eq 'ogg' -and @($_.phrase_ids | Where-Object { $_ -in $manifest.excluded_phrase_ids }).Count -eq 0 } | Sort-Object id)
$candidate=[pscustomobject]@{id='groq-whisper-large-v3';provider='groq';model='whisper-large-v3';endpoint='https://api.groq.com/openai/v1/audio/transcriptions';language='pt';settings=@{response_format='json';prompt_omitted=$true;temperature_default=0}}
$output=Join-Path $root ('docs/avaliacoes/piloto-groq-'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')+'.json')
$round=[ordered]@{version=1;status='piloto_nao_aceito_como_avaliacao_final';started_at_utc=[DateTime]::UtcNow.ToString('o');readings_verified=$false;complete_coverage=$false;attempts_per_file=1;candidates=@($candidate);runs=@()}
$secret=[Environment]::GetEnvironmentVariable('GROQ_API_KEY','Process')
if([string]::IsNullOrWhiteSpace($secret)){throw 'GROQ_API_KEY ausente.'}
$handler=New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect=$false
$client=New-Object System.Net.Http.HttpClient $handler
$client.Timeout=[TimeSpan]::FromSeconds(60)
try{foreach($recording in $active){
    $file=Join-Path $root ('api/src/test/resources/transcricao/'+$recording.file)
    if((Get-FileHash $file -Algorithm SHA256).Hash -ne $recording.sha256){throw 'Hash divergente.'}
    $run=Invoke-TranscriptionAttempt $client $candidate $recording $file $secret 1
    $round.runs+=$run
    Save-TranscriptionRound $round $output
    Write-Output ($recording.id+' HTTP='+$run.http_status+' status='+$run.status)
    if($run.http_status -in @(401,403,429)){break}
    Start-Sleep -Seconds 4
}}finally{$client.Dispose();$secret=$null}
Write-Output ('Evidencia: '+$output)
