param([switch]$SkipModels)
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-Docker { & docker @args; if ($LASTEXITCODE -ne 0) { throw "Docker failed. Read the error above." } }
if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop, start it, then rerun this script.' }
Invoke-Docker info --format '{{.ServerVersion}}'
Invoke-Docker compose version
if (!(Test-Path .env)) { Copy-Item .env.example .env; Write-Host 'Created private .env from the example.' }
Invoke-Docker compose -f docker-compose.yml -f compose.auth.yml config --quiet
if (!$SkipModels) {
    Invoke-Docker compose -f docker-compose.yml -f compose.auth.yml --profile models up -d ollama
    $taskReady=$false
    for($taskAttempt=0;$taskAttempt -lt 30;$taskAttempt++){
        & docker compose -f docker-compose.yml -f compose.auth.yml exec -T ollama ollama list *> $null
        if($LASTEXITCODE -eq 0){$taskReady=$true;break}
        Start-Sleep -Seconds 1
    }
    if(!$taskReady){throw 'Ollama did not start. Check its container logs.'}
    $taskModels=@('llama3.2-vision:11b','llama3.1:8b','nomic-embed-text')
    foreach($taskModel in $taskModels){Invoke-Docker compose -f docker-compose.yml -f compose.auth.yml exec -T ollama ollama pull $taskModel}
}
Invoke-Docker compose -f docker-compose.yml -f compose.auth.yml --profile models up --build -d
Write-Host 'Services started. App: http://localhost:5173 | Reset emails: http://localhost:8025'
Write-Host 'Check readiness: docker compose -f docker-compose.yml -f compose.auth.yml --profile models ps'
if($SkipModels){Write-Host 'Models skipped: classification, extraction, and RAG will not work until models are downloaded.'}

