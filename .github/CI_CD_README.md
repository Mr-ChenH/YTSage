# YTSage CI/CD Workflow

This repository is focused on the self-hosted YTSage server package. Desktop executable packaging has been removed.

## Workflows

- `release-all.yml`: Manual release entry point. It currently delegates to the PyPI package workflow.
- `build-pypi.yml`: Builds the Python source distribution and wheel, then uploads them to a draft GitHub release.
- `star-history.yml`: Updates generated star history assets.

## Creating A Release

1. Go to the repository Actions tab.
2. Select `Create Release`.
3. Click `Run workflow`.
4. Enter a version such as `5.4.5`.
5. Review the draft release after the package artifacts are uploaded.

## Build Notes

The package entry point is:

```text
ytsage = ytsage.server.app:main
```

The package includes the built Web UI from:

```text
ytsage/server/static/
```

Before publishing a release after frontend changes, rebuild the frontend and copy the output into the server static directory:

```bash
npm --prefix frontend run build
rm -rf ytsage/server/static/*
cp -R frontend/dist/* ytsage/server/static/
```

Recommended validation before release:

```bash
python -m py_compile ytsage/server/app.py ytsage/server/models.py ytsage/server/services/download_service.py
npm --prefix frontend run build
python -m build
```
