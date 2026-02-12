# CI/CD

## Multi-Architecture Image Builds

The repository includes a GitHub Actions workflow that builds and publishes multi-architecture Docker images.

**Workflow:** `.github/workflows/docker.yml`

## Trigger Conditions

- Push to `main` branch
- Manual workflow dispatch

**Note:** Pull requests to `development` will not trigger image builds.

## Supported Platforms

- `linux/amd64` - x86_64 architecture
- `linux/arm64` - ARM 64-bit (e.g., Raspberry Pi 4, AWS Graviton)
- `linux/arm/v7` - ARM 32-bit (e.g., Raspberry Pi 3)

## Build Process

1. **Checkout code** - Clones the repository
2. **Set up QEMU** - Enables cross-architecture emulation
3. **Set up Docker Buildx** - Configures multi-platform builds
4. **Login to GHCR** - Authenticates with GitHub Container Registry
5. **Build and push** - Builds images for all platforms and pushes to registry

## Image Tags

Images are tagged with:
- `ghcr.io/autonomy-logic/orchestrator-agent:latest` - Latest build from main
- `ghcr.io/autonomy-logic/orchestrator-agent:<commit-sha>` - Specific commit

## Required Secrets

The workflow requires the following GitHub secrets:
- `GHCR_USERNAME` - GitHub Container Registry username
- `GHCR_TOKEN` - GitHub Container Registry token (with `write:packages` permission)

## Manual Workflow Dispatch

To manually trigger a build:

1. Go to the repository on GitHub
2. Click "Actions" tab
3. Select "Docker Image CI" workflow
4. Click "Run workflow"
5. Select branch (usually `main`)
6. Click "Run workflow" button

## Local Multi-Architecture Builds

To build multi-architecture images locally:

```bash
# Set up buildx
docker buildx create --use

# Build for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t ghcr.io/autonomy-logic/orchestrator-agent:local \
  --push \
  .
```

**Note:** Requires Docker Buildx and QEMU installed.

## Image Registry

Images are published to GitHub Container Registry (GHCR):
- Registry: `ghcr.io`
- Organization: `autonomy-logic`
- Repository: `orchestrator-agent`

## Viewing Build Logs

To view build logs:

1. Go to the repository on GitHub
2. Click "Actions" tab
3. Select the workflow run
4. Click on the build job to view logs

## Build Failures

Common causes of build failures:

**Authentication Errors:**
- Verify `GHCR_USERNAME` and `GHCR_TOKEN` secrets are set correctly
- Ensure token has `write:packages` permission

**Platform Build Errors:**
- Check Dockerfile for platform-specific issues
- Verify dependencies are available for all platforms

**Resource Limits:**
- GitHub Actions runners have limited resources
- Consider optimizing Dockerfile to reduce build time

## Network Monitor Image

The network monitor sidecar has a separate Dockerfile:
- **Dockerfile:** `install/Dockerfile.netmon`
- **Image:** `ghcr.io/autonomy-logic/autonomy-netmon:latest`

Currently, the network monitor image is built manually. Consider adding it to the CI/CD workflow for automated builds.

## Future Improvements

- Add automated testing to CI/CD pipeline
- Add code linting and formatting checks
- Add security scanning for Docker images
- Add automated deployment to staging environment
- Add network monitor image to CI/CD workflow
