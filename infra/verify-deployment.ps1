param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [int]$MinimumListingsPerMode = 25,
  [string]$ProofRunId = "",
  [switch]$RequireEvaluationProof
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
if (-not $Health.observability.bigquery_agent_analytics -or -not $Health.observability.cloud_trace) {
  throw "BigQuery ADK analytics and Cloud Trace are not both enabled in the deployed API."
}

$WebResponse = Invoke-WebRequest -Uri $WebUrl -UseBasicParsing -TimeoutSec 30
if ($WebResponse.StatusCode -ne 200 -or $WebResponse.Content -notmatch "Roamstead") {
  throw "The deployed web service did not return the Roamstead application."
}

$VerificationProfileId = ""
$VerificationListingIds = @()
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
  if ($Mode -eq "BUY") {
    $VerificationProfileId = $Session.session.profile_id
    $VerificationListingIds = @($Search.items | Select-Object -First 3 | ForEach-Object { $_.id })
  }
}

$Watch = Invoke-RestMethod `
  -Method Post `
  -Uri "$ApiUrl/api/v1/decision-watches" `
  -ContentType "application/json" `
  -Body (@{
      profile_id = $VerificationProfileId
      listing_ids = $VerificationListingIds
      idempotency_key = "deployment-verification-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
    } | ConvertTo-Json -Depth 5) `
  -TimeoutSec 90
if ($Watch.watch.status -ne "PROPOSED" -or -not $Watch.watch.approval_required -or @($Watch.revisions).Count -ne 0) {
  throw "Decision Watch did not preserve the explicit approval gate."
}
if ($Watch.watch.plan.degraded -or $Watch.watch.plan.provider -ne "GOOGLE_ADK") {
  throw "Decision Watch fell back instead of persisting a successful live ADK planning result."
}
if (@($Watch.watch.plan.tasks).Count -lt 3 -or @($Watch.watch.plan.tasks).Count -gt 9) {
  throw "DueDiligencePlanner returned an unbounded task plan."
}
foreach ($ListingId in $VerificationListingIds) {
  if (@($Watch.watch.plan.tasks | Where-Object { $_.listing_id -eq $ListingId -and $_.tool -eq "SOURCE_AVAILABILITY" }).Count -ne 1) {
    throw "Decision Watch did not include exactly one source check for $ListingId."
  }
}
$CanceledWatch = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/v1/decision-watches/$($Watch.watch.id)/cancel" -ContentType "application/json" -TimeoutSec 30
if ($CanceledWatch.watch.status -ne "CANCELED" -or $null -ne $CanceledWatch.watch.next_run_at) {
  throw "Decision Watch cancellation did not prevent future execution."
}

gcloud firestore databases describe --project $ProjectId --database "(default)" | Out-Null
$VectorIndexes = @(gcloud firestore indexes composite list --project $ProjectId --database "(default)" --format json | ConvertFrom-Json)
$VectorIndex = $VectorIndexes | Where-Object {
  $_.queryScope -eq "COLLECTION" -and
  @($_.fields | Where-Object { $_.fieldPath -eq "embedding" -and $_.vectorConfig.dimension -eq 768 }).Count -gt 0
} | Select-Object -First 1
if (-not $VectorIndex -or $VectorIndex.state -ne "READY") {
  throw "The Firestore semantic_memory vector index is missing or not READY."
}
gcloud pubsub topics describe roamstead-catalog-events --project $ProjectId | Out-Null
gcloud storage buckets describe "gs://$ProjectId-roamstead-listing-images" --project $ProjectId | Out-Null
gcloud run jobs describe roamstead-weekly-catalog --project $ProjectId --region $Region | Out-Null
gcloud run jobs describe roamstead-agent-eval --project $ProjectId --region $Region | Out-Null
$SchedulerState = gcloud scheduler jobs describe roamstead-weekly-catalog --project $ProjectId --location $Region --format "value(state)"
if ($SchedulerState -ne "PAUSED") {
  throw "The weekly scheduler must remain PAUSED until one bounded maintenance run is measured."
}
bq --project_id=$ProjectId show --dataset "$ProjectId`:roamstead_agent_analytics" | Out-Null

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

if ($RequireEvaluationProof) {
  $Evaluation = Invoke-RestMethod -Uri "$ApiUrl/api/v1/evaluations/latest" -TimeoutSec 30
  if (-not $Evaluation.passed -or -not $Evaluation.hard_gates_passed) {
    throw "The latest persisted evaluation report did not pass every hard gate."
  }
  if (($Evaluation.development_case_count + $Evaluation.validation_case_count) -ne 20) {
    throw "The persisted release evaluation does not contain the required 20 cases."
  }
  $Metrics = @{}
  foreach ($Metric in $Evaluation.metrics) { $Metrics[$Metric.name] = $Metric.score }
  if ($Metrics["response_quality"] -lt 0.85 -or $Metrics["tool_trajectory"] -lt 0.90 -or $Metrics["safety_and_real_data_gates"] -ne 1) {
    throw "The persisted release evaluation missed a response, trajectory, or safety threshold."
  }
}

Write-Output "PASS: Roamstead web, API, ADK/Gemini, both Gemma critics, Gemini Embedding, Firestore vector index, approval-gated Decision Watch, redacted BigQuery analytics, Cloud Trace, real listing inventory, Pub/Sub, Storage, paused Scheduler, and both Cloud Run jobs are deployment-ready."
Write-Output "Web: $WebUrl"
Write-Output "API: $ApiUrl"
