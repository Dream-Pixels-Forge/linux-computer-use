# Goal spec — Issue #8: safe PyPI and GitHub release automation

**Branch:** `chore/8-release-automation` (worktree `/tmp/lcu-issue-8`)
**Issue:** dream-pixels-forge/linux-computer-use#8 — `chore: add safe PyPI and GitHub release automation`
**Package:** `linux-computer-use` (pyproject version `0.1.0`, build backend `poetry.core.masonry.api`)

## Objective

Add one tag- and manually-triggerable release workflow (`.github/workflows/release.yml`) that strictly validates, builds, publishes with PyPI OIDC, creates a GitHub Release, and verifies registry alignment — plus executable contract tests (`tests/unit/test_release_workflow.py`) and release documentation (`docs/releasing.md`).

## Scope (in)

- `.github/workflows/release.yml`: `on.push.tags: ["v*"]` + `on.workflow_dispatch` with required `version` input
- `validate → build → publish → release → verify` job chain
- Strict semver validation; requested version (tag `v*` stripped or dispatch input) must equal `pyproject.toml` `[project].version` exactly
- Manual dispatch only from `main`; tag pushes run for tags on any branch but version is locked to pyproject
- Publish via `pypa/gh-action-pypi-publish@v1.14.2`, `id-token: write`, **no username/password** (OIDC trusted publisher; external setup, see blocker)
- GitHub Release via `softprops/action-gh-release@v3`, artifacts attached
- Least privilege: top-level `contents: read`; per-job `id-token: write` (publish), `contents: write` (release)
- Artifact handoff: `dist-<version>` uploaded by build, downloaded by publish/release/verify with matching names
- Post-publish registry + fresh-venv verification: PyPI JSON API, tag existence, GitHub Release existence, fresh venv `pip install linux-computer-use==<version>` and `importlib.metadata.version` check
- No `|| true` on any quality gate; no long-lived PyPI tokens; no `pypi` GitHub environment referenced
- `docs/releasing.md`: trusted-publisher registration, how to release, version rules, blocker
- `dev-notes/goals/08-release-automation.md` (this file) + independent goal-met audit under `dev-notes/`

## Scope (out)

- No publishing, tagging, pushing, or PR opening as part of this task
- No changes to `main`, no CI weakening, no driver/desktop behavior changes
- No PyPI token or repository secret added by this PR

## Definition of done

- [ ] `tests/unit/test_release_workflow.py` fails on missing/old draft (RED), passes after implementation (GREEN)
- [ ] `ruff check src/python tests`, `mypy src/python`, `pytest tests/unit` green
- [ ] `pnpm typecheck && pnpm build` green (CI not weakened)
- [ ] `python -m build && twine check dist/*` pass in a clean environment
- [ ] Workflow contract: exact action pins, OIDC no-password, semver + pyproject match, main-only manual, artifact name match, concurrency, least privilege

## Verification steps

1. `PYTHONPATH=/tmp/lcu-issue-8/src/python <venv python> -m pytest tests/unit` — inspect RED then GREEN
2. `ruff check src/python tests && mypy src/python`
3. `pnpm typecheck && pnpm build`
4. `python -m build && twine check dist/*`
5. Read `docs/releasing.md` for trusted-publisher blocker instructions

## External blocker (do not bypass)

PyPI trusted publisher for `linux-computer-use` (OIDC: GitHub repo + workflow) and any `pypi` environment must be created in PyPI/GitHub settings by a maintainer before the first real release. This PR adds only the workflow, tests, and docs.
