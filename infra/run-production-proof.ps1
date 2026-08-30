param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [int]$RunCount = 3
)

$ErrorActionPreference = "Stop"

if ($RunCount -lt 3) {
  throw "Production proof requires at least three consecutive runs."
}
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw "Google Cloud CLI (gcloud) is required."
}
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
  throw "curl.exe is required to consume the Decision Brief event stream."
}

$ApiUrl = gcloud run services describe roamstead-api `
  --project $ProjectId `
  --region $Region `
  --format "value(status.url)"
if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
  throw "The roamstead-api Cloud Run URL could not be resolved."
}

$ProofRunIds = @()
for ($Index = 1; $Index -le $RunCount; $Index++) {
  Write-Output "Starting production proof $Index of $RunCount..."
  $Session = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiUrl/api/v1/sessions" `
    -ContentType "application/json" `
    -Body (@{ housing_mode = "BUY" } | ConvertTo-Json) `
    -TimeoutSec 30
  $Search = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiUrl/api/v1/listings/search" `
    -ContentType "application/json" `
    -Body (@{
        transaction_mode = "BUY"
        profile_id = $Session.session.profile_id
        limit = 100
      } | ConvertTo-Json) `
    -TimeoutSec 60

  $ListingIds = @($Search.items | Select-Object -First 3 | ForEach-Object { $_.id })
  if ($ListingIds.Count -ne 3) {
    throw "Proof $Index could not select exactly three qualified real listings."
  }

  $Queued = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiUrl/api/v1/decision-briefs" `
    -ContentType "application/json" `
    -Body (@{
        profile_id = $Session.session.profile_id
        listing_ids = $ListingIds
        idempotency_key = "production-proof-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())-$Index"
      } | ConvertTo-Json -Depth 5) `
    -TimeoutSec 30
  $RunId = $Queued.run.id
  if ([string]::IsNullOrWhiteSpace($RunId)) {
    throw "Proof $Index did not return a persisted run ID."
  }

  # Consuming this stream starts the durable workflow and waits for its terminal event.
  & curl.exe --fail --silent --show-error --no-buffer `
    --max-time 180 `
    --output NUL `
    "$ApiUrl/api/v1/decision-briefs/$RunId/events"
  if ($LASTEXITCODE -ne 0) {
    throw "Proof $Index event stream failed or exceeded 180 seconds. Run ID: $RunId"
  }

  $Brief = Invoke-RestMethod -Uri "$ApiUrl/api/v1/decision-briefs/$RunId" -TimeoutSec 30
  $ExpectedModels = @("gemini-embedding-001", "gemma-4-26b-a4b-it", "gemma-4-31b-it")
  $MissingModels = @($ExpectedModels | Where-Object { $Brief.models_used -notcontains $_ })
  if (
    $Brief.status -ne "COMPLETED" -or
    $Brief.degraded -or
    $Brief.memory_context.status -ne "READY" -or
    -not $Brief.visual_audit.succeeded -or
    -not $Brief.memory_audit.succeeded -or
    $MissingModels.Count -gt 0
  ) {
    throw "Proof $Index is degraded or missing successful model evidence. Run ID: $RunId"
  }

  $ProofRunIds += $RunId
  Write-Output "PASS: $RunId"
}

$EvaluationProofRunId = $ProofRunIds[-1]
Write-Output "Running the 20-case ADK evaluation against $EvaluationProofRunId..."
gcloud run jobs execute roamstead-agent-eval `
  --project $ProjectId `
  --region $Region `
  --args "scripts/run_agent_evaluation.py,--proof-run-id,$EvaluationProofRunId" `
  --wait
if ($LASTEXITCODE -ne 0) {
  throw "The ADK evaluation job failed. No quality proof should be claimed."
}

& "$PSScriptRoot/verify-deployment.ps1" `
  -ProjectId $ProjectId `
  -Region $Region `
  -ProofRunId $EvaluationProofRunId `
  -RequireEvaluationProof
if ($LASTEXITCODE -ne 0) {
  throw "Final deployment verification failed."
}

Write-Output "PASS: three consecutive production proofs and the persisted 20-case evaluation passed."
Write-Output "Proof run IDs: $($ProofRunIds -join ', ')"
Write-Output "Evaluation proof run: $EvaluationProofRunId"
