#!/bin/sh
# Builds the image, pushes it to Yandex Container Registry and rolls out a new revision of
# the serverless container with the settings from .env.cloud.
# Usage: deploy/yandex/deploy.sh
set -eu
cd "$(dirname "$0")/../.."
REGISTRY=${REGISTRY:?id of the container registry}
SERVICE_ACCOUNT=${SERVICE_ACCOUNT:?id of the service account that pulls the image}
CONTAINER=${CONTAINER:-silomery}
TAG="cr.yandex/$REGISTRY/silomery:$(date +%Y%m%d-%H%M%S)"

yc iam create-token | docker login --username iam --password-stdin cr.yandex >/dev/null
# Yandex's registry wants a plain Docker manifest: no attestations, no OCI media types.
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
    --output "type=image,name=$TAG,push=true,oci-mediatypes=false" .

yc serverless container revision deploy --container-name "$CONTAINER" --image "$TAG" \
    --cores 1 --core-fraction 100 --memory 512MB --concurrency 8 --execution-timeout 300s \
    --service-account-id "$SERVICE_ACCOUNT" \
    --command uvicorn \
    --args 'app.api.main:create_app,--factory,--host,0.0.0.0,--port,8080,--proxy-headers,--forwarded-allow-ips,*' \
    --environment "$(grep -E '^[A-Z_]+=' .env.cloud | paste -sd, -)" >/dev/null
echo "deployed $TAG"
