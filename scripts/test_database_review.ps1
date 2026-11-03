param([string]$ContainerName = 'homeflow-db-combined-review')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-ReviewDocker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed. Stop and inspect the output above.' }
}
Invoke-ReviewDocker info --format '{{.ServerVersion}}'
$existing = & docker ps -a --format '{{.Names}}'
if ($LASTEXITCODE -ne 0) { throw 'Could not list containers.' }
if ($existing -contains $ContainerName) {
    throw "Container $ContainerName already exists. Use a different -ContainerName; nothing was deleted."
}
$initPath = (Resolve-Path .\db\init).Path
Invoke-ReviewDocker run -d --name $ContainerName -e POSTGRES_USER=homeflow -e POSTGRES_PASSWORD=review_only -e POSTGRES_DB=review --mount "type=bind,source=$initPath,target=/docker-entrypoint-initdb.d,readonly" pgvector/pgvector:pg16
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $state = & docker inspect --format '{{.State.Running}}' $ContainerName
    if ($state -ne 'true') { break }
    # Initialization uses a socket-only temporary server. TCP readiness waits for the final server.
    & docker exec $ContainerName pg_isready -h 127.0.0.1 -U homeflow -d review *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (!$ready) { & docker logs $ContainerName; throw 'Fresh database did not become ready. No existing HomeFlow storage was used.' }
Invoke-ReviewDocker cp .\db\tests "${ContainerName}:/tests"
$tests = @('test_file_application_ownership.sql', 'test_document_chunk_ownership.sql', 'test_file_metadata_checks.sql', 'test_source_file_relationships.sql', 'test_source_file_customer_ownership.sql', 'test_auth_rules.sql')
foreach ($test in $tests) {
    Write-Host "Running $test"
    Invoke-ReviewDocker exec $ContainerName psql -U homeflow -d review -v ON_ERROR_STOP=1 -f "/tests/$test"
}
Write-Host 'PASS: fresh initialization and all six SQL test scripts completed.'
Write-Host "Test container retained: $ContainerName. It exposes no host port and uses its own anonymous data volume."
Write-Host 'Still pending: existing-database upgrade, full backend tests, and uploaded document workflow.'
