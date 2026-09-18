# Accountable Surface Release Checklist

This repository ships a reviewed GitHub `v0.2.0` source release and local
package artifacts from commit `b2ae9be77038753d9bdbda861e9908542883ff2c`. A
package-registry upload is still a separate release decision because
`coherence-membrane` and `proof-surface` are documented sibling source
dependencies, not PyPI dependencies.

Do not replace release assets, create a PyPI project, or add a registry upload
until the exact release head and evidence below have been reviewed.

## Release Head

Start from public `main` in a clean checkout or an isolated release worktree:

```powershell
git fetch origin main
git switch main
git pull --ff-only origin main
git status --short --branch
```

The `v0.2.0` GitHub release head is
`b2ae9be77038753d9bdbda861e9908542883ff2c`. The source metadata, README, usage
guide, changelog, and this checklist name `0.2.0`; later releases should repeat
that consistency check before publishing.

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

For the 0.2.0 authority release, also run a private synthetic durable-authority
control with a disposable authority-state database only. The release proof may
exercise `accountable-surface-authority --help`, `doctor`, and local recovery
state on synthetic data. It must not revoke a real grant, recover production
state, call external APIs, or actuate against a live third-party target.

## Package Build

Build locally into a fresh artifact directory:

```powershell
python -m build --sdist --wheel --outdir dist-0.2.0
Get-FileHash dist-0.2.0\accountable_surface-0.2.0.tar.gz,dist-0.2.0\accountable_surface-0.2.0-py3-none-any.whl -Algorithm SHA256
```

Check the artifacts with a Twine version that accepts current core metadata:

```powershell
python -m pip install --upgrade "twine>=7"
python -m twine check dist-0.2.0\accountable_surface-0.2.0.tar.gz dist-0.2.0\accountable_surface-0.2.0-py3-none-any.whl
```

If an older local Twine rejects metadata version `2.5`, upgrade the checker rather
than weakening build metadata.

## Proof Install

Create a fresh virtual environment, install the built wheel, and supply only the
sibling source paths:

```powershell
python -m venv .venv-install-proof
.\.venv-install-proof\Scripts\python.exe -m pip install --upgrade pip
.\.venv-install-proof\Scripts\python.exe -m pip install dist-0.2.0\accountable_surface-0.2.0-py3-none-any.whl
$env:PYTHONPATH = "..\coherence-membrane\src;..\proof-surface\src"
.\.venv-install-proof\Scripts\python.exe -c "import accountable_surface; print(accountable_surface.__version__)"
.\.venv-install-proof\Scripts\accountable-surface-authority.exe --help
.\.venv-install-proof\Scripts\accountable-surface-server.exe --help
```

For a stronger proof, run an offline `FilesystemEffector` actuation in the fresh
environment and a synthetic durable-authority state control against temp files.
Do not use `ApiEffector`, browser, command, UIA, or any live third-party effector
as the install proof.

## Publication Routes

Current repository state has CI only. It does not ship a registry-publish workflow.

For the current GitHub source release, `v0.2.0` is published with
`SHA256SUMS.txt`, the wheel, and the sdist attached. For later GitHub releases,
prepare release notes from `CHANGELOG.md`, attach the hash list if artifacts are
included, and create the tag only after review.

For a package-registry release, either:

- upload the checked `dist-0.2.0` artifacts from a clean release machine, or
- add a reviewed trusted-publishing workflow after the PyPI project/environment is
  configured.

In both cases, keep the claim narrow: version `0.2.0` is an alpha local action
workbench with default-deny grants, bounded effectors, verification, rollback where
available, MCP integration, durable authority state for remote MCP actuation, and
tamper-evident journals. It is not a safety certification, model-alignment result,
third-party service endorsement, race-proof authority service, rollback-proof
custody service, or proof that every host environment behaves safely.
