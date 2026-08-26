param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [int]$MinimumListingsPerMode = 25,
  [string]$ProofRunId = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw "Google Cloud CLI (gcloud) is required."
}

$ApiUrl = gcloud run services describe roamstead-api --project $ProjectId --region $Region --format "value(status.url)"
$WebUrl = gcloud run services describe roamstead-web --project $ProjectId --region $Region --format "value(status.url)"
if ([string]::IsNullOrWhiteSpace($ApiUrl) -or [string]::IsNullOrWhiteSpace($WebUrl)) {
  throw "Cloud Run service URLs could not be resolved."
}

$Health = Invoke-RestMethod -Uri "$ApiUrl/health" -TimeoutSec 30
if ($Health.status -ne "ok" -or $Health.deployment_mode -ne "CLOUD_RUN") {
  throw "API health check did not prove a healthy Cloud Run deployment."
}
if ($Health.agent.execution_mode -ne "ADK_GEMINI") {
  throw "Google ADK/Gemini is not enabled in the deployed API."
}
if (-not $Health.agent.gemma_critic.enabled) {
  throw "Gemma VisualEvidenceCritic is not enabled."
}
if (-not $Health.agent.memory_critic.enabled -or $Health.agent.memory_critic.model -ne "gemma-4-31b-it") {
  throw "Gemma MemoryConsistencyCritic is not enabled with the expected model."
}
if (-not $Health.agent.semantic_memory.enabled -or $Health.agent.semantic_memory.model -ne "gemini-embedding-001" -or $Health.agent.semantic_memory.dimension -ne 768) {
  throw "The 768-dimensional Gemini Embedding semantic-memory integration is not enabled."
}
if ($Health.persistence -notlike "Firestore primary*") {
  throw "The API is not reporting Firestore as its primary persistence mode."
}

$WebResponse = Invoke-WebRequest -Uri $WebUrl -UseBasicParsing -TimeoutSec 30
if ($WebResponse.StatusCode -ne 200 -or $WebResponse.Content -notmatch "Roamstead") {
  throw "The deployed web service did not return the Roamstead application."
}

foreach ($Mode in @("BUY", "RENT")) {
  $Session = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiUrl/api/v1/sessions" `
    -ContentType "application/json" `
    -Body (@{ housing_mode = $Mode } | ConvertTo-Json) `
    -TimeoutSec 30
  $Search = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiUrl/api/v1/listings/search" `
    -ContentType "application/json" `
    -Body (@{ transaction_mode = $Mode; profile_id = $Session.session.profile_id; limit = 100 } | ConvertTo-Json) `
    -TimeoutSec 60
  if ($Search.returned -lt $MinimumListingsPerMode) {
    throw "$Mode returned $($Search.returned) listings; expected at least $MinimumListingsPerMode. Run and inspect the catalog job before promotion."
  }
  if (@($Search.items | Where-Object { $_.demo -ne $false -or $_.source_domain -ne "batdongsan.com.vn" }).Count -gt 0) {
    throw "$Mode returned a listing that failed the real-data-only source contract."
  }
}

gcloud firestore databases describe --project $ProjectId --database "(default)" | Out-Null
$VectorIndex = gcloud firestore indexes composite list --project $ProjectId --database "(default)" --filter "collectionGroup:semantic_memory AND fields.fieldPath:embedding" --format "value(state)" --limit 1
if ($VectorIndex -ne "READY") {
  throw "The Firestore semantic_memory vector index is missing or not READY."
}
gcloud pubsub topics describe roamstead-catalog-events --project $ProjectId | Out-Null
gcloud storage buckets describe "gs://$ProjectId-roamstead-listing-images" --project $ProjectId | Out-Null
gcloud run jobs describe roamstead-weekly-catalog --project $ProjectId --region $Region | Out-Null

if (-not [string]::IsNullOrWhiteSpace($ProofRunId)) {
  $Brief = Invoke-RestMethod -Uri "$ApiUrl/api/v1/decision-briefs/$ProofRunId" -TimeoutSec 30
  $ExpectedModels = @("gemini-embedding-001", "gemma-4-26b-a4b-it", "gemma-4-31b-it")
  foreach ($Model in $ExpectedModels) {
    if ($Brief.models_used -notcontains $Model) { throw "Proof run does not contain successful model output from $Model." }
  }
  if ($Brief.degraded -or $Brief.memory_context.status -ne "READY" -or -not $Brief.visual_audit.succeeded -or -not $Brief.memory_audit.succeeded) {
    throw "Proof run is degraded or missing a successful persisted audit."
  }
}

Write-Output "PASS: Roamstead web, API, ADK/Gemini, both Gemma critics, Gemini Embedding, Firestore vector index, real listing inventory, Pub/Sub, Storage, and weekly job are deployment-ready."
Write-Output "Web: $WebUrl"
Write-Output "API: $ApiUrl"
