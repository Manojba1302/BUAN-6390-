param([ValidateSet('start','stop','status','logs','test')][string]$Action='start')
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$taskCompose=@('compose','-f','docker-compose.yml','-f','compose.auth.yml','--profile','models')
switch($Action){
  start { & docker @taskCompose up -d }
  stop { & docker @taskCompose down }
  status { & docker @taskCompose ps }
  logs { & docker @taskCompose logs -f backend worker }
  test { & docker @taskCompose run --rm --no-deps backend python tests/auth_test.py }
}
if($LASTEXITCODE -ne 0){throw 'Docker command failed.'}
