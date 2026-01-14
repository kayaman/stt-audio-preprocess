#!/bin/bash
# =============================================================================
# Deploy Audio Preprocessing Service to Azure Container Apps
# =============================================================================
#
# Prerequisites:
#   - Azure CLI installed and logged in
#   - Docker installed (for building)
#   - Azure Container Registry (ACR) created
#
# Usage:
#   ./deploy.sh [environment]
#
# Example:
#   ./deploy.sh production
#
# =============================================================================

set -e

# Configuration
ENVIRONMENT="${1:-production}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-audio-preprocess-${ENVIRONMENT}}"
LOCATION="${LOCATION:-eastus}"
ACR_NAME="${ACR_NAME:-acraudiopreprocess}"
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-cae-audio-preprocess-${ENVIRONMENT}}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-ca-audio-preprocess}"
IMAGE_NAME="audio-preprocess"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-staudiopreprocess${ENVIRONMENT}}"

echo "=============================================="
echo "Deploying Audio Preprocessing Service"
echo "=============================================="
echo "Environment:      ${ENVIRONMENT}"
echo "Resource Group:   ${RESOURCE_GROUP}"
echo "Location:         ${LOCATION}"
echo "ACR:              ${ACR_NAME}"
echo "Image:            ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Storage Account:  ${STORAGE_ACCOUNT}"
echo "=============================================="

# -----------------------------------------------------------------------------
# Step 1: Create Resource Group
# -----------------------------------------------------------------------------
echo "Creating resource group..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none

# -----------------------------------------------------------------------------
# Step 2: Create Storage Account
# -----------------------------------------------------------------------------
echo "Creating storage account..."
az storage account create \
  --name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --output none

# Get connection string
STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
  --name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query connectionString \
  --output tsv)

# Create containers and queue
echo "Creating storage containers..."
az storage container create \
  --name audio-input \
  --connection-string "${STORAGE_CONNECTION_STRING}" \
  --output none || true

az storage container create \
  --name audio-output \
  --connection-string "${STORAGE_CONNECTION_STRING}" \
  --output none || true

az storage queue create \
  --name audio-processing-queue \
  --connection-string "${STORAGE_CONNECTION_STRING}" \
  --output none || true

# -----------------------------------------------------------------------------
# Step 3: Create ACR (if not exists)
# -----------------------------------------------------------------------------
echo "Creating container registry..."
az acr create \
  --name "${ACR_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --sku Basic \
  --admin-enabled true \
  --output none || true

# -----------------------------------------------------------------------------
# Step 4: Build and Push Image
# -----------------------------------------------------------------------------
echo "Building and pushing image..."
az acr build \
  --registry "${ACR_NAME}" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  --image "${IMAGE_NAME}:latest" \
  --file Dockerfile \
  .

# Get ACR credentials
ACR_LOGIN_SERVER=$(az acr show --name "${ACR_NAME}" --query loginServer --output tsv)
ACR_USERNAME=$(az acr credential show --name "${ACR_NAME}" --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name "${ACR_NAME}" --query "passwords[0].value" --output tsv)

# -----------------------------------------------------------------------------
# Step 5: Create Container Apps Environment
# -----------------------------------------------------------------------------
echo "Creating Container Apps environment..."
az containerapp env create \
  --name "${CONTAINER_APP_ENV}" \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none || true

# -----------------------------------------------------------------------------
# Step 6: Deploy Container App
# -----------------------------------------------------------------------------
echo "Deploying container app..."
az containerapp create \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --environment "${CONTAINER_APP_ENV}" \
  --image "${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}" \
  --registry-server "${ACR_LOGIN_SERVER}" \
  --registry-username "${ACR_USERNAME}" \
  --registry-password "${ACR_PASSWORD}" \
  --target-port 8080 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 10 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --secrets \
    "storage-connection-string=${STORAGE_CONNECTION_STRING}" \
  --env-vars \
    "AZURE_STORAGE_CONNECTION_STRING=secretref:storage-connection-string" \
    "AZURE_CONTAINER_INPUT=audio-input" \
    "AZURE_FOLDER_INPUT=incoming" \
    "AZURE_CONTAINER_OUTPUT=audio-output" \
    "AZURE_FOLDER_OUTPUT=processed" \
    "AZURE_QUEUE_NAME=audio-processing-queue" \
    "AZURE_DELETE_SOURCE=true" \
    "PROCESSING_MODE=queue" \
    "VAD_ENABLED=true" \
    "VAD_THRESHOLD=0.5" \
    "NOISE_ENABLED=false" \
    "SILENCE_ENABLED=true" \
    "NORMALIZE_ENABLED=true" \
    "ENVIRONMENT=${ENVIRONMENT}" \
    "DEBUG=false" \
  --query properties.configuration.ingress.fqdn \
  --output tsv

echo "=============================================="
echo "Deployment complete!"
echo "=============================================="

# Get the FQDN
FQDN=$(az containerapp show \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

echo "Service URL: https://${FQDN}"
echo "Health check: https://${FQDN}/health"
echo "Metrics: https://${FQDN}/metrics"
echo ""
echo "To set up Event Grid for blob triggers, run:"
echo "  ./setup-eventgrid.sh ${RESOURCE_GROUP} ${STORAGE_ACCOUNT}"
