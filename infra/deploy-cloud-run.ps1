param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [string]$MapsBrowserApiKey = $env:ROAMSTEAD_MAPS_BROWSER_API_KEY,
  [string]$MapsMapId = $env:ROAMSTEAD_MAPS_MAP_ID,
  [switch]$EnableWeeklyScheduler
)

$ErrorActionPreference = "Stop"
$ArtifactRepo = "roamstead"
$ApiImage = "$Region-docker.pkg.dev/$ProjectId/$ArtifactRepo/api:latest"
$WebImage = "$Region-docker.pkg.dev/$ProjectId/$ArtifactRepo/web:latest"
$ImageBucket = "$ProjectId-roamstead-listing-images"
$ApiServiceAccount = "roamstead-api@$ProjectId.iam.gserviceaccount.com"
$RefreshServiceAccount = "roamstead-refresh@$ProjectId.iam.gserviceaccount.com"
$SchedulerServiceAccount = "roamstead-scheduler@$ProjectId.iam.gserviceaccount.com"
$EvaluatorServiceAccount = "roamstead-evaluator@$ProjectId.iam.gserviceaccount.com"
$AnalyticsDataset = "roamstead_agent_analytics"
$EvaluationBucket = "$ProjectId-roamstead-agent-evaluations"

function Test-GcloudResource([string[]]$Arguments) {
  $PreviousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  try {
    & gcloud @Arguments *> $null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $PreviousPreference
  }
}

function Test-BqResource([string[]]$Arguments) {
  $PreviousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  try {
    & bq @Arguments *> $null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $PreviousPreference
  }
}

function Assert-LastCommand([string]$Message) {
  if ($LASTEXITCODE -ne 0) { throw $Message }
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw "Google Cloud CLI (gcloud) is required. Install it and authenticate before deployment."
}
if (-not (Get-Command bq -ErrorAction SilentlyContinue)) {
  throw "The BigQuery bq CLI component is required for the ADK analytics dataset."
}
if ([string]::IsNullOrWhiteSpace($MapsBrowserApiKey)) {
  throw "Set ROAMSTEAD_MAPS_BROWSER_API_KEY to a browser-restricted Google Maps key before deployment."
}

gcloud config set project $ProjectId
gcloud projects describe $ProjectId --format "value(projectId)" | Out-Null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com pubsub.googleapis.com storage.googleapis.com aiplatform.googleapis.com maps-backend.googleapis.com geocoding-backend.googleapis.com bigquery.googleapis.com bigquerystorage.googleapis.com cloudtrace.googleapis.com

if (-not (Test-GcloudResource @("artifacts", "repositories", "describe", $ArtifactRepo, "--location", $Region))) {
  gcloud artifacts repositories create $ArtifactRepo --repository-format docker --location $Region
}

foreach ($account in @("roamstead-api", "roamstead-refresh", "roamstead-scheduler", "roamstead-evaluator")) {
  if (-not (Test-GcloudResource @("iam", "service-accounts", "describe", "$account@$ProjectId.iam.gserviceaccount.com"))) {
    gcloud iam service-accounts create $account --display-name $account
  }
}
foreach ($role in @("roles/datastore.user", "roles/bigquery.jobUser", "roles/cloudtrace.agent")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$ApiServiceAccount" --role $role --condition None
}
foreach ($role in @("roles/datastore.user", "roles/bigquery.jobUser")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$EvaluatorServiceAccount" --role $role --condition None
}

foreach ($role in @("roles/datastore.user")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$ApiServiceAccount" --role $role --condition None
}
foreach ($role in @("roles/datastore.user")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$RefreshServiceAccount" --role $role --condition None
}

if (-not (Test-GcloudResource @("pubsub", "topics", "describe", "roamstead-catalog-events"))) {
  gcloud pubsub topics create roamstead-catalog-events
}

if (-not (Test-GcloudResource @("storage", "buckets", "describe", "gs://$ImageBucket"))) {
  gcloud storage buckets create "gs://$ImageBucket" --location $Region --uniform-bucket-level-access
}
if (-not (Test-GcloudResource @("storage", "buckets", "describe", "gs://$EvaluationBucket"))) {
  gcloud storage buckets create "gs://$EvaluationBucket" --location $Region --uniform-bucket-level-access
}

if (-not (Test-BqResource @("--project_id=$ProjectId", "show", "--dataset", "$ProjectId`:$AnalyticsDataset"))) {
  bq --project_id=$ProjectId --location=US mk --dataset "$ProjectId`:$AnalyticsDataset"
}
gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$ApiServiceAccount" --role roles/bigquery.dataEditor --condition None | Out-Null
gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$EvaluatorServiceAccount" --role roles/bigquery.dataViewer --condition None | Out-Null
if (-not (Test-BqResource @("--project_id=$ProjectId", "show", "$ProjectId`:$AnalyticsDataset.evaluation_candidates"))) {
  bq --project_id=$ProjectId mk --table "$ProjectId`:$AnalyticsDataset.evaluation_candidates" "run_id:STRING,reason:STRING,status:STRING,curated_at:TIMESTAMP"
}

if (-not (Test-GcloudResource @("secrets", "describe", "roamstead-gemini-api-key"))) {
  throw "Create Secret Manager secret roamstead-gemini-api-key before deployment; never pass the key on the command line."
}
$EnabledSecretVersion = gcloud secrets versions list roamstead-gemini-api-key --filter "state=ENABLED" --limit 1 --format "value(name)"
if ([string]::IsNullOrWhiteSpace($EnabledSecretVersion)) {
  throw "Secret roamstead-gemini-api-key exists but has no enabled version."
}
if (-not (Test-GcloudResource @("firestore", "databases", "describe", "--database", "(default)"))) {
  throw "Create the default Firestore database in Native mode first; its location is a project-level choice."
}

$ExistingIndexes = @(gcloud firestore indexes composite list --database "(default)" --format json | ConvertFrom-Json)
$VectorIndex = $ExistingIndexes | Where-Object { @($_.fields | Where-Object { $_.fieldPath -eq "embedding" }).Count -gt 0 } | Select-Object -First 1
if (-not $VectorIndex) {
  gcloud firestore indexes composite create --database "(default)" --collection-group semantic_memory --query-scope collection --field-config "field-path=profile_id,order=ascending" --field-config "field-path=embedding,vector-config={dimension=768,flat}"
}

gcloud secrets add-iam-policy-binding roamstead-gemini-api-key --member "serviceAccount:$ApiServiceAccount" --role roles/secretmanager.secretAccessor | Out-Null
gcloud secrets add-iam-policy-binding roamstead-gemini-api-key --member "serviceAccount:$RefreshServiceAccount" --role roles/secretmanager.secretAccessor | Out-Null
gcloud secrets add-iam-policy-binding roamstead-gemini-api-key --member "serviceAccount:$EvaluatorServiceAccount" --role roles/secretmanager.secretAccessor | Out-Null
gcloud pubsub topics add-iam-policy-binding roamstead-catalog-events --member "serviceAccount:$ApiServiceAccount" --role roles/pubsub.publisher | Out-Null
gcloud pubsub topics add-iam-policy-binding roamstead-catalog-events --member "serviceAccount:$RefreshServiceAccount" --role roles/pubsub.publisher | Out-Null
gcloud storage buckets add-iam-policy-binding "gs://$ImageBucket" --member "serviceAccount:$ApiServiceAccount" --role roles/storage.objectViewer | Out-Null
gcloud storage buckets add-iam-policy-binding "gs://$ImageBucket" --member "serviceAccount:$RefreshServiceAccount" --role roles/storage.objectAdmin | Out-Null
gcloud storage buckets add-iam-policy-binding "gs://$EvaluationBucket" --member "serviceAccount:$EvaluatorServiceAccount" --role roles/storage.objectAdmin | Out-Null

gcloud builds submit apps/api --region $Region --tag $ApiImage
Assert-LastCommand "API image build failed; deployment stopped before creating a revision."
gcloud run deploy roamstead-api --image $ApiImage --region $Region --service-account $ApiServiceAccount --allow-unauthenticated --cpu 1 --memory 1Gi --concurrency 20 --timeout 300 --min-instances 0 --max-instances 1 --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,VERTEX_LOCATION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,LISTING_IMAGE_BUCKET=$ImageBucket,PUBSUB_TOPIC=roamstead-catalog-events,ENABLE_ADK_AGENT=1,ENABLE_GEMMA_CRITIC=1,ENABLE_SEMANTIC_MEMORY=1,ENABLE_MEMORY_CRITIC=1,ENABLE_WEEKLY_LISTING_REFRESH=0,ROAMSTEAD_GEMINI_MODEL=gemini-3.5-flash,ROAMSTEAD_GEMMA_MODEL=gemma-4-26b-a4b-it,ROAMSTEAD_EMBEDDING_MODEL=gemini-embedding-001,ROAMSTEAD_EMBEDDING_DIMENSION=768,ROAMSTEAD_MEMORY_TOP_K=5,ROAMSTEAD_MEMORY_MAX_CHARS=6000,ROAMSTEAD_MEMORY_MAX_COSINE_DISTANCE=0.30,ROAMSTEAD_MEMORY_CRITIC_MODEL=gemma-4-31b-it,GEMMA_PHOTOS_PER_LISTING=1,GEMMA_CRITIC_TIMEOUT_SECONDS=45,MEMORY_CRITIC_TIMEOUT_SECONDS=45,ADK_SPECIALIST_TIMEOUT_SECONDS=45,ROAMSTEAD_WORKFLOW_VERSION=partner-coordinator-v2,ROAMSTEAD_PROMPT_VERSION=preference-interpreter-v1,ENABLE_BIGQUERY_AGENT_ANALYTICS=1,ROAMSTEAD_AGENT_ANALYTICS_DATASET=$AnalyticsDataset,ROAMSTEAD_AGENT_ANALYTICS_TABLE=agent_events,ROAMSTEAD_AGENT_ANALYTICS_LOCATION=US,ENABLE_CLOUD_TRACE=1,ROAMSTEAD_WATCH_INTERVAL_DAYS=7,ROAMSTEAD_WATCH_MAX_PER_RUN=5,ROAMSTEAD_WATCH_HTTP_TIMEOUT_SECONDS=8"
Assert-LastCommand "API Cloud Run deployment failed."
$ApiUrl = gcloud run services describe roamstead-api --region $Region --format "value(status.url)"
if ([string]::IsNullOrWhiteSpace($ApiUrl)) { throw "API Cloud Run URL could not be resolved." }

gcloud builds submit apps/web --region $Region --config apps/web/cloudbuild.yaml --substitutions "_API_URL=$ApiUrl,_IMAGE=$WebImage,_MAPS_BROWSER_API_KEY=$MapsBrowserApiKey,_MAPS_MAP_ID=$MapsMapId"
Assert-LastCommand "Web image build failed; deployment stopped before creating a revision."
gcloud run deploy roamstead-web --image $WebImage --region $Region --allow-unauthenticated --cpu 1 --memory 512Mi --concurrency 80 --timeout 300 --min-instances 0 --max-instances 1 --set-env-vars "API_URL=$ApiUrl"
Assert-LastCommand "Web Cloud Run deployment failed."
$WebUrl = gcloud run services describe roamstead-web --region $Region --format "value(status.url)"
if ([string]::IsNullOrWhiteSpace($WebUrl)) { throw "Web Cloud Run URL could not be resolved." }
gcloud run services update roamstead-api --region $Region --update-env-vars "WEB_ORIGIN=$WebUrl"
Assert-LastCommand "API origin update failed."

if (Test-GcloudResource @("run", "jobs", "describe", "roamstead-weekly-catalog", "--region", $Region)) {
  gcloud run jobs update roamstead-weekly-catalog --image $ApiImage --region $Region --service-account $RefreshServiceAccount --cpu 1 --memory 2Gi --task-timeout 3600s --max-retries 1 --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,VERTEX_LOCATION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,LISTING_IMAGE_BUCKET=$ImageBucket,PUBSUB_TOPIC=roamstead-catalog-events,ENABLE_ADK_AGENT=1,ENABLE_WEEKLY_LISTING_REFRESH=0,ENABLE_CATALOG_REFRESH_IN_MAINTENANCE=1,ROAMSTEAD_GEMINI_MODEL=gemini-3.5-flash,ROAMSTEAD_WATCH_INTERVAL_DAYS=7,ROAMSTEAD_WATCH_MAX_PER_RUN=5,ROAMSTEAD_WATCH_HTTP_TIMEOUT_SECONDS=8" --command python --args "scripts/run_weekly_maintenance.py"
} else {
  gcloud run jobs create roamstead-weekly-catalog --image $ApiImage --region $Region --service-account $RefreshServiceAccount --cpu 1 --memory 2Gi --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,VERTEX_LOCATION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,LISTING_IMAGE_BUCKET=$ImageBucket,PUBSUB_TOPIC=roamstead-catalog-events,ENABLE_ADK_AGENT=1,ENABLE_WEEKLY_LISTING_REFRESH=0,ENABLE_CATALOG_REFRESH_IN_MAINTENANCE=1,ROAMSTEAD_GEMINI_MODEL=gemini-3.5-flash,ROAMSTEAD_WATCH_INTERVAL_DAYS=7,ROAMSTEAD_WATCH_MAX_PER_RUN=5,ROAMSTEAD_WATCH_HTTP_TIMEOUT_SECONDS=8" --command python --args "scripts/run_weekly_maintenance.py" --task-timeout 3600s --max-retries 1
}

$EvalEnvironment = "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,ROAMSTEAD_EVALUATION_BUCKET=$EvaluationBucket,ROAMSTEAD_AGENT_ANALYTICS_DATASET=$AnalyticsDataset,ROAMSTEAD_AGENT_ANALYTICS_TABLE=agent_events,ROAMSTEAD_WORKFLOW_VERSION=partner-coordinator-v2,ROAMSTEAD_PROMPT_VERSION=preference-interpreter-v1,ROAMSTEAD_GEMINI_MODEL=gemini-3.5-flash,ENABLE_ADK_AGENT=1"
if (Test-GcloudResource @("run", "jobs", "describe", "roamstead-agent-eval", "--region", $Region)) {
  gcloud run jobs update roamstead-agent-eval --image $ApiImage --region $Region --service-account $EvaluatorServiceAccount --cpu 1 --memory 2Gi --task-timeout 3600s --max-retries 0 --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars $EvalEnvironment --command python --args "scripts/run_agent_evaluation.py"
} else {
  gcloud run jobs create roamstead-agent-eval --image $ApiImage --region $Region --service-account $EvaluatorServiceAccount --cpu 1 --memory 2Gi --task-timeout 3600s --max-retries 0 --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars $EvalEnvironment --command python --args "scripts/run_agent_evaluation.py"
}

gcloud run jobs add-iam-policy-binding roamstead-weekly-catalog --region $Region --member "serviceAccount:$SchedulerServiceAccount" --role roles/run.invoker
$JobUri = "https://run.googleapis.com/v2/projects/$ProjectId/locations/$Region/jobs/roamstead-weekly-catalog`:run"
if (Test-GcloudResource @("scheduler", "jobs", "describe", "roamstead-weekly-catalog", "--location", $Region)) {
  gcloud scheduler jobs update http roamstead-weekly-catalog --location $Region --schedule "0 9 * * 1" --time-zone "Etc/UTC" --uri $JobUri --http-method POST --oauth-service-account-email $SchedulerServiceAccount
} else {
  gcloud scheduler jobs create http roamstead-weekly-catalog --location $Region --schedule "0 9 * * 1" --time-zone "Etc/UTC" --uri $JobUri --http-method POST --oauth-service-account-email $SchedulerServiceAccount
}
if ($EnableWeeklyScheduler) {
  gcloud scheduler jobs resume roamstead-weekly-catalog --location $Region --quiet
} else {
  gcloud scheduler jobs pause roamstead-weekly-catalog --location $Region --quiet
}

Write-Output "Roamstead web: $WebUrl"
Write-Output "Roamstead API: $ApiUrl"
Write-Output "Evaluation job: roamstead-agent-eval (manual only; execute with a successful proof run ID override)."
Write-Output "Weekly catalog scheduler: $(if ($EnableWeeklyScheduler) { 'enabled' } else { 'paused for cost control; pass -EnableWeeklyScheduler after measuring one refresh' })."
Write-Output "Next: seed the verified local snapshot with apps/api/scripts/seed_cloud_from_local.py, then run infra/verify-deployment.ps1."
