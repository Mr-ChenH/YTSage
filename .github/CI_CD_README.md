# YTSage CI/CD Workflows

This repository publishes the self-hosted Python package, Web UI, and Docker image. Desktop executable packaging has been removed.

## Workflows

- `docker-publish.yml`: Validates the backend and frontend, then builds and pushes the Docker image to GitHub Container Registry.
- `release-all.yml`: Manual release entry point for Python release artifacts.
- `build-pypi.yml`: Builds the Python source distribution and wheel, then uploads them to a draft GitHub release.
- `star-history.yml`: Updates generated star history assets.

## Docker Publishing

The image name is derived from the repository owner and name:

```text
ghcr.io/<owner>/<repository>
```

For this repository, deployments use:

```text
ghcr.io/mr-chenh/ytsage
```

A push to `main` publishes these tags:

- `latest`
- the version from `pyproject.toml`, such as `5.5.0`
- `sha-<commit>`

A pushed `v*` Git tag publishes `latest`, semantic-version tags, and the immutable commit SHA tag. The workflow can also be run manually from the Actions page.

The workflow authenticates with the built-in `GITHUB_TOKEN`; repository Actions permissions must allow package writes. After the first run, confirm the container package is public in the repository Packages settings so unauthenticated Docker and Compose clients can pull it.

## Creating A Python Release

1. Update the version in `pyproject.toml`.
2. Go to the repository Actions tab.
3. Select `Create Release`.
4. Click `Run workflow`.
5. Enter the same version, such as `5.5.0`.
6. Review the draft release after the package artifacts are uploaded.

## Build Notes

The package entry point is:

```text
ytsage = ytsage.server.app:main
```

The package includes the built Web UI from:

```text
ytsage/server/static/
```

Before publishing a Python release after frontend changes, rebuild the frontend and copy the output into the server static directory:

```bash
npm --prefix frontend run build
rm -rf ytsage/server/static/*
cp -R frontend/dist/* ytsage/server/static/
```

Recommended local validation before release:

```bash
python -m pytest -q
python -m compileall -q ytsage tests
npm --prefix frontend run build
python -m build
```
