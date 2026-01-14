#!/bin/bash
# =============================================================================
# Set up Event Grid to route blob events to Storage Queue
# =============================================================================
#
# This creates an Event Grid subscription that:
#   - Triggers on BlobCreated events in the input container
#   - Sends events to the Storage Queue for processing
#
# Usage:
#   ./setup-eventgrid.sh <resource-group> <storage-account>
#
# =============================================================================

set -e

RESOURCE_GROUP="${1:?Resource group required}"
STORAGE_ACCOUNT="${2:?Storage account required}"
SUBSCRIPTION_NAME="audio-blob-created"
INPUT_CONTAINER="audio-input"
INPUT_FOLDER="incoming"
QUEUE_NAME="audio-processing-queue"

echo "=============================================="
echo "Setting up Event Grid for Blob Triggers"
echo "=============================================="
echo "Resource Group:  ${RESOURCE_GROUP}"
echo "Storage Account: ${STORAGE_ACCOUNT}"
echo "Queue:           ${QUEUE_NAME}"
echo "=============================================="

# Get storage account ID
STORAGE_ID=$(az storage account show \
  --name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query id \
  --output tsv)

# Get storage connection string
CONNECTION_STRING=$(az storage account show-connection-string \
  --name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query connectionString \
  --output tsv)

# Get queue endpoint
QUEUE_ENDPOINT="https://${STORAGE_ACCOUNT}.queue.core.windows.net/${QUEUE_NAME}"

# Get storage account key for queue auth
STORAGE_KEY=$(az storage account keys list \
  --account-name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query "[0].value" \
  --output tsv)

echo "Creating Event Grid subscription..."

# Create Event Grid system topic (if not exists)
az eventgrid system-topic create \
  --name "${STORAGE_ACCOUNT}-topic" \
  --resource-group "${RESOURCE_GROUP}" \
  --source "${STORAGE_ID}" \
  --topic-type Microsoft.Storage.StorageAccounts \
  --location "$(az storage account show --name ${STORAGE_ACCOUNT} --resource-group ${RESOURCE_GROUP} --query location --output tsv)" \
  --output none 2>/dev/null || true

# Create subscription to route events to queue
az eventgrid system-topic event-subscription create \
  --name "${SUBSCRIPTION_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --system-topic-name "${STORAGE_ACCOUNT}-topic" \
  --endpoint-type storagequeue \
  --endpoint "${STORAGE_ID}/queueServices/default/queues/${QUEUE_NAME}" \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with "/blobServices/default/containers/${INPUT_CONTAINER}/blobs/${INPUT_FOLDER}" \
  --advanced-filter data.contentType StringContains audio \
  --output none

echo "=============================================="
echo "Event Grid setup complete!"
echo "=============================================="
echo ""
echo "Events will be routed as follows:"
echo "  Trigger: BlobCreated in ${INPUT_CONTAINER}/${INPUT_FOLDER}/"
echo "  Filter:  Content type contains 'audio'"
echo "  Target:  Storage Queue '${QUEUE_NAME}'"
echo ""
echo "To test, upload an audio file:"
echo "  az storage blob upload \\"
echo "    --account-name ${STORAGE_ACCOUNT} \\"
echo "    --container-name ${INPUT_CONTAINER} \\"
echo "    --name ${INPUT_FOLDER}/test.wav \\"
echo "    --file test.wav"
