# Accountable Surface Release Checklist

This repository can support a first public GitHub source release and local package
artifacts for version `0.1.0`. A package-registry upload is a separate release
decision because `coherence-membrane` and `proof-surface` are documented sibling
source dependencies, not PyPI dependencies.

Do not create a tag, GitHub release, PyPI project, or registry upload until the
exact release head and the evidence below have been reviewed.

## Release Head

Start from public `main` in a clean checkout:

```powershell
git fetch origin main
git switch main
git pull --ff-only origin main
git status --short --branch
```

The release head must match the commit recorded in the release receipt.

## Verification

Use sibling checkouts of `coherence-membrane` and `proof-surface`:

```powershell
$env:PYTHONPATH = "src;..\coherence-membrane\src;..\proof-surface\src"
python -m pip install -e ".[test,server]"
python -m pytest
node --test web/*.test.mjs
python tools\check_repo_art.py --json
python tools\check_repo_card.py
python tools\check_repo_flow.py
```

The MCP `actuate` surface is default-deny unless the operator exposes effectors
through `ACCOUNTABLE_SURFACE_EFFECTORS`. Do not include private grant files,
journals, credentials, caches, transcripts, or live third-party action receipts in
release artifacts.

## Package Build

Build locally:

```powershell
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
python -m build --sdist --wheel
Get-FileHash dist\accountable_surface-0.1.0.tar.gz,dist\accountable_surface-0.1.0-py3-none-any.whl -Algorithm SHA256
```

Check the artifacts with a Twine version that accepts current core metadata:

```powershell
python -m pip install --upgrade "twine>=7"
python -m twine check dist\accountable_surface-0.1.0.tar.gz dist\accountable_surface-0.1.0-py3-none-any.whl
```

If an older local Twine rejects metadata version `2.5`, upgrade the checker rather
than weakening build metadata.

## Proof Install

Create a fresh virtual environment, install the built wheel, and supply only the
sibling source paths:

```powershell
python -m venv .venv-install-proof
.\.venv-install-proof\Scripts\python.exe -m pip install --upgrade pip
.\.venv-install-proof\Scripts\python.exe -m pip install dist\accountable_surface-0.1.0-py3-none-any.whl
$env:PYTHONPATH = "..\coherence-membrane\src;..\proof-surface\src"
.\.venv-install-proof\Scripts\python.exe -c "import accountable_surface; print(accountable_surface.__version__)"
```

For a stronger proof, run an offline `FilesystemEffector` actuation in the fresh
environment. Do not use `ApiEffector`, browser, command, UIA, or any live
third-party effector as the install proof.

## Publication Routes

Current repository state has CI only. It does not ship a registry-publish workflow.

For a GitHub source release, prepare release notes from `CHANGELOG.md`, attach the
hash list if artifacts are included, and create the tag only after review.

For a package-registry release, either:

- upload the checked `dist` artifacts from a clean release machine, or
- add a reviewed trusted-publishing workflow after the PyPI project/environment is
  configured.

In both cases, keep the claim narrow: version `0.1.0` is an alpha local action
workbench with default-deny grants, bounded effectors, verification, rollback where
available, MCP integration, and tamper-evident journals. It is not a safety
certification, model-alignment result, third-party service endorsement, or proof
that every host environment behaves safely.
