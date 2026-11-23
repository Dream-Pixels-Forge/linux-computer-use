# Releasing `linux-computer-use`

This document describes how the `linux-computer-use` PyPI package is released.
All releases go through `.github/workflows/release.yml`; there is no manual
`twine upload` path and no long-lived PyPI token.

## Version rule

The release version **must equal** `[project].version` in `pyproject.toml`
(exactly, e.g. `0.1.0`) and must be a strict semver release version. The tag
is always `v<version>` (e.g. `v0.1.0`).

## Two ways to cut a release

### 1. Tag push (recommended)

On `main`:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The `push.tags: ["v*"]` trigger starts the workflow, which validates the tag
against `pyproject.toml`, builds, publishes, creates the GitHub Release, and
verifies.

### 2. Manual dispatch

Go to GitHub → Actions → "Release" → "Run workflow", enter the version (must
match `pyproject.toml`), and run it. Manual dispatches are only allowed from
`main`; the workflow creates and pushes the annotated tag `v<version>`
itself if it does not exist yet.

## What the workflow does

1. **validate** — reads `pyproject.toml`, accepts only strict semver, requires
   the requested version to equal `[project].version`; manual dispatch is
   rejected unless `github.ref` is `refs/heads/main`.
2. **build** — `python -m build` (sdist + wheel), uploads `dist-<version>`.
3. **publish** — `pypa/gh-action-pypi-publish@v1.14.2` with OIDC
   (`id-token: write`); **no username/password**.
4. **release** — `softprops/action-gh-release@v3` creates the GitHub Release
   and attaches the build artifacts.
5. **verify** — checks the PyPI JSON registry, the tag, the GitHub Release,
   then installs the package in a fresh venv and asserts its metadata version.

## External blocker: PyPI trusted publisher (one-time setup)

Before the first release, a maintainer must register a **PyPI trusted
publisher** for project `linux-computer-use`:

- Trusted publisher: GitHub repository `dream-pixels-forge/linux-computer-use`
- OIDC audience/issuer from the `publish` job (`id-token: write`); no
  `pypi` GitHub environment is referenced by the workflow.
- Pattern match: `refs/tags/v*` (and the release workflow) if PyPI asks.

Do **not** bypass this with a long-lived PyPI API token; report the missing
trusted publisher as a blocker instead.

## What not to do

- Do not publish manually (`twine upload`, `python -m build --outdir dist`
  followed by manual upload) — the workflow is the single publication path.
- Do not add `pypi` passwords/tokens to repository or environment secrets.
- Do not push `v*` tags from anything other than this workflow's contract.
