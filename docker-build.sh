#!/bin/bash
# Build and push Ferelix Server Docker image to Docker Hub

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    exit 1
fi

# Get version from git tag or default to 'dev'
VERSION=${1:-dev}
DOCKERHUB_USERNAME=${DOCKERHUB_USERNAME:-}

# Prompt for Docker Hub username if not set
if [ -z "$DOCKERHUB_USERNAME" ]; then
    read -p "Enter your Docker Hub username: " DOCKERHUB_USERNAME
fi

IMAGE_NAME="${DOCKERHUB_USERNAME}/ferelix-server"

echo -e "${GREEN}Building Ferelix Server Docker Image${NC}"
echo "Version: ${VERSION}"
echo "Image: ${IMAGE_NAME}"
echo ""

# Login to Docker Hub
echo -e "${YELLOW}Logging in to Docker Hub...${NC}"
docker login

# Build multi-platform image
echo -e "${YELLOW}Building multi-platform image (amd64, arm64)...${NC}"
docker buildx create --use --name ferelix-builder 2>/dev/null || docker buildx use ferelix-builder

# Build and push
if [ "$VERSION" = "dev" ]; then
    echo -e "${YELLOW}Building development image (local only)...${NC}"
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --tag "${IMAGE_NAME}:dev" \
        --load \
        .
    echo -e "${GREEN}Development image built: ${IMAGE_NAME}:dev${NC}"
else
    echo -e "${YELLOW}Building and pushing version ${VERSION}...${NC}"
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --tag "${IMAGE_NAME}:${VERSION}" \
        --tag "${IMAGE_NAME}:latest" \
        --push \
        .
    echo -e "${GREEN}Images pushed to Docker Hub:${NC}"
    echo "  - ${IMAGE_NAME}:${VERSION}"
    echo "  - ${IMAGE_NAME}:latest"
fi

# Cleanup
docker buildx rm ferelix-builder 2>/dev/null || true

echo ""
echo -e "${GREEN}✓ Build complete!${NC}"
echo ""
echo "To use this image:"
echo "  docker pull ${IMAGE_NAME}:${VERSION}"
echo ""
echo "Or update your docker-compose.yml:"
echo "  image: ${IMAGE_NAME}:${VERSION}"
