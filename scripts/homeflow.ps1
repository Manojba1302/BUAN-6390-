param([ValidateSet('start','stop','status','logs','test','test-db')][string]$Action='start')
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$taskCompose=@('compose','-f','docker-compose.yml','-f','compose.auth.yml','--profile','models')
switch($Action){
  start { & docker @taskCompose up -d }
  stop { & docker @taskCompose down }
  status { & docker @taskCompose ps }
  logs { & docker @taskCompose logs -f backend worker }
  test { & docker @taskCompose run --rm --no-deps backend python -m unittest tests.auth_test tests.classifier_test tests.logic_test tests.code_standards_test }
  'test-db' { & docker @taskCompose run --rm -e HOMEFLOW_DB_TEST=1 backend python -m unittest tests.postgres_test }
}
if($LASTEXITCODE -ne 0){throw 'Docker command failed.'}
