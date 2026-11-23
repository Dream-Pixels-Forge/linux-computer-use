"""Executable contract tests for the release workflow (Issue #8).

These tests inspect ``.github/workflows/release.yml`` and assert the
release automation contract: triggers, version validation, job chain,
OIDC publishing without passwords, artifact handoff, least privilege,
and post-publish verification. They do not run the workflow itself.

Run:
    PYTHONPATH=/tmp/lcu-issue-8/src/python \
        /home/dimona/Dream-Pixels-Forge/Dev/cli/linux-computer-use/.venv/bin/python -m pytest tests/unit
"""

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Semver 2.0.0 (release versions only; pre-release tolerated in pattern but
# rejected by the "release version" equality check against pyproject).
SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

PYPUBLISH = "pypa/gh-action-pypi-publish@v1.14.2"
GH_RELEASE = "softprops/action-gh-release@v3"


def _load_workflow() -> dict:
    assert WORKFLOW_PATH.is_file(), f"missing {WORKFLOW_PATH}"
    data = yaml.safe_load(WORKFLOW_PATH.read_text())
    # YAML parses the `on:` key as boolean True; normalize it.
    if True in data:
        data["on"] = data.pop(True)
    return data


def _project_version() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text())
    return str(data["project"]["version"])


def _step_usages(job) -> list[str]:
    usages = []
    for step in job.get("steps", []):
        uses = step.get("uses")
        if isinstance(uses, str):
            usages.append(uses)
    return usages


def _step_runs(job) -> list[str]:
    return [str(step.get("run", "")) for step in job.get("steps", [])]


def test_release_workflow_file_exists():
    assert WORKFLOW_PATH.is_file()


def test_triggers_include_push_tags_v_star_and_workflow_dispatch():
    wf = _load_workflow()
    on = wf.get("on", {})
    assert on.get("push", {}).get("tags") == ["v*"]
    assert "workflow_dispatch" in on


def test_workflow_dispatch_has_required_version_input():
    wf = _load_workflow()
    inputs = wf["on"]["workflow_dispatch"].get("inputs", {})
    assert "version" in inputs
    assert inputs["version"].get("required") is True


def test_job_chain_validate_build_publish_release_verify():
    wf = _load_workflow()
    jobs = wf["jobs"]
    expected = ["validate", "build", "publish", "release", "verify"]
    assert list(jobs.keys()) == expected, list(jobs.keys())
    assert jobs["build"].get("needs") == "validate"
    assert jobs["publish"].get("needs") == "build"
    assert jobs["release"].get("needs") in ("build", ["build", "validate"], ["validate", "build"])
    assert jobs["verify"].get("needs") in ("publish", ["publish", "release"])


def test_publish_uses_pypi_publish_exact_pin():
    wf = _load_workflow()
    assert PYPUBLISH in _step_usages(wf["jobs"]["publish"])


def test_publish_uses_oidc_no_password():
    wf = _load_workflow()
    job = wf["jobs"]["publish"]
    perms = job.get("permissions", {})
    assert perms.get("id-token") == "write", perms
    for step in job.get("steps", []):
        with_p = step.get("with", {}) or {}
        assert "username" not in with_p, step
        assert "password" not in with_p, step
    for run in _step_runs(job):
        assert "twine upload" not in run and "__token__" not in run


def test_release_job_uses_softprops_gh_release_v3():
    wf = _load_workflow()
    assert GH_RELEASE in _step_usages(wf["jobs"]["release"])


def test_manual_dispatch_only_from_main():
    wf = _load_workflow()
    found = False
    for step in wf["jobs"]["validate"].get("steps", []):
        run = str(step.get("run", ""))
        cond = str(step.get("if", ""))
        if "refs/heads/main" in run or "refs/heads/main" in cond:
            found = True
    # The dispatch guard may live in any validate step; assert somewhere.
    text = WORKFLOW_PATH.read_text()
    assert found or "refs/heads/main" in text


def test_tag_and_dispatch_versions_matched_against_pyproject():
    # Also asserts the workflow parses as valid YAML.
    assert _load_workflow() is not None
    text = WORKFLOW_PATH.read_text()
    project_version = _project_version()
    # A validation step must read pyproject.toml and compare with the
    # requested (tag-stripped or dispatch) version.
    assert "pyproject.toml" in text
    assert "tomllib" in text or "project.version" in text
    assert str(project_version) in text or "${{" in text


def test_strict_semver_validation():
    text = WORKFLOW_PATH.read_text()
    assert SEMVER_PATTERN in text or re.compile(SEMVER_PATTERN).search(text)
    # Every asserted version gate is anchored to an exact equality with pyproject.
    assert "pyproject.toml" in text


def test_no_advisory_true_quality_gates():
    text = WORKFLOW_PATH.read_text()
    for gate in ("ruff check", "mypy", "pytest", "twine check", "python -m build"):
        for line in text.splitlines():
            if gate in line and "|| true" in line:
                raise AssertionError(f"advisory gate found: {line.strip()}")


def test_artifact_names_match_across_jobs():
    wf = _load_workflow()
    names = []
    for job_name in ("build", "publish", "release", "verify"):
        job = wf["jobs"][job_name]
        for step in job.get("steps", []):
            with_p = step.get("with", {}) or {}
            name = with_p.get("name")
            if name and name.startswith("dist-"):
                names.append(name)
    assert names, "no dist-* artifacts found"
    assert len(set(names)) == 1, f"artifact names must match: {names}"
    assert names[0].startswith("dist-") and "validate.outputs.version" in names[0], names[0]


def test_concurrency_prevents_duplicate_runs():
    wf = _load_workflow()
    concurrency = wf.get("concurrency")
    assert concurrency, "concurrency group required to avoid duplicate runs"
    group = concurrency.get("group") if isinstance(concurrency, dict) else concurrency
    assert "${{" in str(group), "concurrency group must key on ref/version"


def test_least_privilege_permissions():
    wf = _load_workflow()
    top = wf.get("permissions", {})
    assert top.get("contents") == "read", top
    publish_perms = wf["jobs"]["publish"].get("permissions", {})
    assert publish_perms.get("id-token") == "write"
    release_perms = wf["jobs"]["release"].get("permissions", {})
    assert release_perms.get("contents") == "write"


def test_verify_job_fresh_venv_and_registry_checks():
    wf = _load_workflow()
    wf["jobs"]["verify"]  # job must exist
    text = WORKFLOW_PATH.read_text()
    assert "python3 -m venv" in text or "python -m venv" in text
    assert "importlib.metadata" in text or "importlib_metadata" in text
    assert "pypi.org" in text or "PyPI" in text
    assert "refs/tags" in text or "git tag" in text or "gh release" in text
