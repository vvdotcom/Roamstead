param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [string]$ServiceName = "roamstead-gemma-critic",
  [string]$ModelName = "google/gemma-4-E4B-it"
)

$ErrorActionPreference = "Stop"
$ApiServiceAccount = "roamstead-api@$ProjectId.iam.gserviceaccount.com"
$Image = "us-docker.pkg.dev/vertex-ai/vertex-vision-model-garden-dockers/pytorch-vllm-serve:gemma4"
$ContainerArgs = @(
  "serve",
  $ModelName,
  "--enable-chunked-prefill",
  "--enable-prefix-caching",
  "--generation-config=auto",
  "--enable-auto-tool-choice",
  "--tool-call-parser=gemma4",
  "--reasoning-parser=gemma4",
  "--dtype=bfloat16",
  "--max-num-seqs=64",
  "--gpu-memory-utilization=0.95",
  "--tensor-parallel-size=1",
  "--port=8080",
  "--host=0.0.0.0"
)

gcloud config set project $ProjectId
gcloud services enable run.googleapis.com

# Mirrors Google's Gemma 4 + ADK Cloud Run guide. The service stays private;
# only the Roamstead API identity receives invocation permission.
gcloud beta run deploy $ServiceName `
  --image $Image `
  --project $ProjectId `
  --region $Region `
  --execution-environment gen2 `
  --no-allow-unauthenticated `
  --cpu 20 `
  --memory 80Gi `
  --gpu 1 `
  --gpu-type nvidia-rtx-pro-6000 `
  --no-gpu-zonal-redundancy `
  --no-cpu-throttling `
  --max-instances 3 `
  --concurrency 64 `
  --timeout 600 `
  --startup-probe "tcpSocket.port=8080,initialDelaySeconds=240,failureThreshold=1,timeoutSeconds=240,periodSeconds=240" `
  --command vllm `
  --args ($ContainerArgs -join ",")

gcloud run services add-iam-policy-binding $ServiceName `
  --region $Region `
  --member "serviceAccount:$ApiServiceAccount" `
  --role roles/run.invoker

$GemmaUrl = gcloud run services describe $ServiceName --region $Region --format "value(status.url)"
gcloud run services update roamstead-api `
  --region $Region `
  --update-env-vars "ENABLE_GEMMA_CRITIC=1,GEMMA_CRITIC_URL=$GemmaUrl,GEMMA_CRITIC_AUDIENCE=$GemmaUrl,GEMMA_CRITIC_AUTH=iam,ROAMSTEAD_GEMMA_MODEL=$ModelName"

Write-Output "Private Gemma critic: $GemmaUrl"
Write-Output "Roamstead API now authenticates to Gemma with its Cloud Run service identity."
