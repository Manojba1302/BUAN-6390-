param([ValidateSet('start','stop','status','logs','test','test-db','test-worker','models','doctor','eval','eval-compare')][string]$Action='start',
      [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest=@())
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$taskCompose=@('compose','-f','docker-compose.yml','-f','compose.auth.yml','--profile','models')
$dockerOllama=(Test-Path .env) -and (Select-String -Path .env -Pattern '^OLLAMA_BASE_URL=http://ollama:' -Quiet)
switch($Action){
  start { if($dockerOllama){ & docker @taskCompose up -d } else { & docker @taskCompose up -d db rabbitmq minio backend worker frontend mailpit } }
  stop { & docker @taskCompose down }
  status { & docker @taskCompose ps }
  logs { & docker @taskCompose logs -f backend worker }
  test { & docker @taskCompose run --rm --no-deps backend python -m unittest tests.auth_test tests.classifier_test tests.logic_test tests.code_standards_test }
  'test-db' { & docker @taskCompose run --rm -e HOMEFLOW_DB_TEST=1 backend python -m unittest tests.postgres_test }
  'test-worker' { & docker @taskCompose run --rm --no-deps worker python -m unittest discover -s tests }
  models { if($dockerOllama){ & docker @taskCompose up -d ollama }
    foreach($model in @('gemma3:4b','llama3.1:8b','nomic-embed-text') + $Rest){ if($dockerOllama){ & docker @taskCompose exec -T ollama ollama pull $model } else { & ollama pull $model }; if($LASTEXITCODE -ne 0){throw "Could not pull $model."} } }
  doctor { & docker @taskCompose run --rm --no-deps worker python -m worker.doctor }
  eval { if($dockerOllama){ & docker @taskCompose up -d ollama }; & docker @taskCompose run --rm --no-deps worker python -m evaluation.run @Rest }
  'eval-compare' { & docker @taskCompose run --rm --no-deps worker python -m evaluation.compare @Rest }
}
if($LASTEXITCODE -ne 0){throw 'Docker command failed.'}
