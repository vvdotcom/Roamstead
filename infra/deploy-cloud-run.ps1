param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [string]$MapsBrowserApiKey = $env:ROAMSTEAD_MAPS_BROWSER_API_KEY,
  [string]$MapsMapId = $env:ROAMSTEAD_MAPS_MAP_ID
)

$ErrorActionPreference = "Stop"
$ArtifactRepo = "roamstead"
$ApiImage = "$Region-docker.pkg.dev/$ProjectId/$ArtifactRepo/api:latest"
$WebImage = "$Region-docker.pkg.dev/$ProjectId/$ArtifactRepo/web:latest"
$ImageBucket = "$ProjectId-roamstead-listing-images"
$ApiServiceAccount = "roamstead-api@$ProjectId.iam.gserviceaccount.com"
$RefreshServiceAccount = "roamstead-refresh@$ProjectId.iam.gserviceaccount.com"
$SchedulerServiceAccount = "roamstead-scheduler@$ProjectId.iam.gserviceaccount.com"

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw "Google Cloud CLI (gcloud) is required. Install it and authenticate before deployment."
}
if ([string]::IsNullOrWhiteSpace($MapsBrowserApiKey)) {
  throw "Set ROAMSTEAD_MAPS_BROWSER_API_KEY to a browser-restricted Google Maps key before deployment."
}

gcloud config set project $ProjectId
gcloud projects describe $ProjectId --format "value(projectId)" | Out-Null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com pubsub.googleapis.com storage.googleapis.com aiplatform.googleapis.com maps-backend.googleapis.com geocoding-backend.googleapis.com

gcloud artifacts repositories describe $ArtifactRepo --location $Region 2>$null
if ($LASTEXITCODE -ne 0) { gcloud artifacts repositories create $ArtifactRepo --repository-format docker --location $Region }

foreach ($account in @("roamstead-api", "roamstead-refresh", "roamstead-scheduler")) {
  gcloud iam service-accounts describe "$account@$ProjectId.iam.gserviceaccount.com" 2>$null
  if ($LASTEXITCODE -ne 0) { gcloud iam service-accounts create $account --display-name $account }
}

foreach ($role in @("roles/datastore.user")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$ApiServiceAccount" --role $role --condition None
}
foreach ($role in @("roles/datastore.user")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$RefreshServiceAccount" --role $role --condition None
}

gcloud pubsub topics describe roamstead-catalog-events 2>$null
if ($LASTEXITCODE -ne 0) { gcloud pubsub topics create roamstead-catalog-events }

gcloud storage buckets describe "gs://$ImageBucket" 2>$null
if ($LASTEXITCODE -ne 0) { gcloud storage buckets create "gs://$ImageBucket" --location $Region --uniform-bucket-level-access }

gcloud secrets describe roamstead-gemini-api-key 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "Create Secret Manager secret roamstead-gemini-api-key before deployment; never pass the key on the command line."
}
$EnabledSecretVersion = gcloud secrets versions list roamstead-gemini-api-key --filter "state=ENABLED" --limit 1 --format "value(name)"
if ([string]::IsNullOrWhiteSpace($EnabledSecretVersion)) {
  throw "Secret roamstead-gemini-api-key exists but has no enabled version."
}
gcloud firestore databases describe --database "(default)" 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "Create the default Firestore database in Native mode first; its location is a project-level choice."
}

$VectorIndex = gcloud firestore indexes composite list --database "(default)" --filter "collectionGroup:semantic_memory AND fields.fieldPath:embedding" --format "value(name)" --limit 1
if ([string]::IsNullOrWhiteSpace($VectorIndex)) {
  gcloud firestore indexes composite create --database "(default)" --collection-group semantic_memory --query-scope collection --field-config "field-path=profile_id,order=ascending" --field-config "field-path=embedding,vector-config={dimension=768,flat}"
}

gcloud secrets add-iam-policy-binding roamstead-gemini-api-key --member "serviceAccount:$ApiServiceAccount" --role roles/secretmanager.secretAccessor | Out-Null
gcloud secrets add-iam-policy-binding roamstead-gemini-api-key --member "serviceAccount:$RefreshServiceAccount" --role roles/secretmanager.secretAccessor | Out-Null
gcloud pubsub topics add-iam-policy-binding roamstead-catalog-events --member "serviceAccount:$ApiServiceAccount" --role roles/pubsub.publisher | Out-Null
gcloud pubsub topics add-iam-policy-binding roamstead-catalog-events --member "serviceAccount:$RefreshServiceAccount" --role roles/pubsub.publisher | Out-Null
gcloud storage buckets add-iam-policy-binding "gs://$ImageBucket" --member "serviceAccount:$ApiServiceAccount" --role roles/storage.objectViewer | Out-Null
gcloud storage buckets add-iam-policy-binding "gs://$ImageBucket" --member "serviceAccount:$RefreshServiceAccount" --role roles/storage.objectAdmin | Out-Null

gcloud builds submit apps/api --region $Region --tag $ApiImage
gcloud run deploy roamstead-api --image $ApiImage --region $Region --service-account $ApiServiceAccount --allow-unauthenticated --cpu 2 --memory 2Gi --concurrency 20 --timeout 300 --min-instances 0 --max-instances 3 --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,VERTEX_LOCATION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,LISTING_IMAGE_BUCKET=$ImageBucket,PUBSUB_TOPIC=roamstead-catalog-events,ENABLE_ADK_AGENT=1,ENABLE_GEMMA_CRITIC=1,ENABLE_SEMANTIC_MEMORY=1,ENABLE_MEMORY_CRITIC=1,ENABLE_WEEKLY_LISTING_REFRESH=0,ROAMSTEAD_GEMINI_MODEL=gemini-3.5-flash,ROAMSTEAD_GEMMA_MODEL=gemma-4-26b-a4b-it,ROAMSTEAD_EMBEDDING_MODEL=gemini-embedding-001,ROAMSTEAD_EMBEDDING_DIMENSION=768,ROAMSTEAD_MEMORY_TOP_K=5,ROAMSTEAD_MEMORY_MAX_CHARS=6000,ROAMSTEAD_MEMORY_MAX_COSINE_DISTANCE=0.30,ROAMSTEAD_MEMORY_CRITIC_MODEL=gemma-4-31b-it,GEMMA_PHOTOS_PER_LISTING=1,GEMMA_CRITIC_TIMEOUT_SECONDS=45,MEMORY_CRITIC_TIMEOUT_SECONDS=45,ADK_SPECIALIST_TIMEOUT_SECONDS=45"
$ApiUrl = gcloud run services describe roamstead-api --region $Region --format "value(status.url)"

gcloud builds submit apps/web --region $Region --config apps/web/cloudbuild.yaml --substitutions "_API_URL=$ApiUrl,_IMAGE=$WebImage,_MAPS_BROWSER_API_KEY=$MapsBrowserApiKey,_MAPS_MAP_ID=$MapsMapId"
gcloud run deploy roamstead-web --image $WebImage --region $Region --allow-unauthenticated --cpu 1 --memory 512Mi --concurrency 80 --timeout 300 --min-instances 0 --max-instances 3 --set-env-vars "API_URL=$ApiUrl"
$WebUrl = gcloud run services describe roamstead-web --region $Region --format "value(status.url)"
gcloud run services update roamstead-api --region $Region --update-env-vars "WEB_ORIGIN=$WebUrl"

gcloud run jobs describe roamstead-weekly-catalog --region $Region 2>$null
if ($LASTEXITCODE -eq 0) {
  gcloud run jobs update roamstead-weekly-catalog --image $ApiImage --region $Region --service-account $RefreshServiceAccount --cpu 2 --memory 4Gi --task-timeout 3600s --max-retries 1 --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,VERTEX_LOCATION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,LISTING_IMAGE_BUCKET=$ImageBucket,PUBSUB_TOPIC=roamstead-catalog-events,ENABLE_ADK_AGENT=1,ENABLE_WEEKLY_LISTING_REFRESH=0" --command python --args "scripts/refresh_catalog.py,--mode,ALL"
} else {
  gcloud run jobs create roamstead-weekly-catalog --image $ApiImage --region $Region --service-account $RefreshServiceAccount --cpu 2 --memory 4Gi --set-secrets "GEMINI_API_KEY=roamstead-gemini-api-key:latest" --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,VERTEX_LOCATION=$Region,FIRESTORE_DATABASE=(default),PERSISTENCE_BACKEND=firestore,LISTING_IMAGE_BUCKET=$ImageBucket,PUBSUB_TOPIC=roamstead-catalog-events,ENABLE_ADK_AGENT=1,ENABLE_WEEKLY_LISTING_REFRESH=0" --command python --args "scripts/refresh_catalog.py,--mode,ALL" --task-timeout 3600s --max-retries 1
}

gcloud run jobs add-iam-policy-binding roamstead-weekly-catalog --region $Region --member "serviceAccount:$SchedulerServiceAccount" --role roles/run.invoker
$JobUri = "https://run.googleapis.com/v2/projects/$ProjectId/locations/$Region/jobs/roamstead-weekly-catalog`:run"
gcloud scheduler jobs describe roamstead-weekly-catalog --location $Region 2>$null
if ($LASTEXITCODE -eq 0) {
  gcloud scheduler jobs update http roamstead-weekly-catalog --location $Region --schedule "0 9 * * 1" --time-zone "Etc/UTC" --uri $JobUri --http-method POST --oauth-service-account-email $SchedulerServiceAccount
} else {
  gcloud scheduler jobs create http roamstead-weekly-catalog --location $Region --schedule "0 9 * * 1" --time-zone "Etc/UTC" --uri $JobUri --http-method POST --oauth-service-account-email $SchedulerServiceAccount
}

Write-Output "Roamstead web: $WebUrl"
Write-Output "Roamstead API: $ApiUrl"
Write-Output "Next: run the first catalog seed with 'gcloud run jobs execute roamstead-weekly-catalog --region $Region --wait', then run infra/verify-deployment.ps1."
