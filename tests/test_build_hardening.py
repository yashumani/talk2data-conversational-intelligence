from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from scripts import dependencies, validate_workflows


@pytest.fixture
def locked_root(tmp_path):
    (tmp_path / "requirements").mkdir()
    for path in dependencies.INPUTS:
        (tmp_path / path).write_text("# synthetic dependency input\n")
    for profile in dependencies.PROFILES:
        (tmp_path / f"requirements/{profile}.txt").write_text("# synthetic lock\n")
    (tmp_path / dependencies.MANIFEST).write_text(json.dumps(dependencies.manifest(tmp_path)))
    return tmp_path


def test_checked_in_locks_match_inputs_and_keep_cloud_packages_optional():
    dependencies.check(dependencies.ROOT)
    runtime = (dependencies.ROOT / "requirements/runtime.txt").read_text()
    internal = (dependencies.ROOT / "requirements/internal.txt").read_text()
    for package in ("duckdb==", "google-cloud-bigquery==", "pyjwt=="):
        assert package not in runtime
        assert package in internal
    assert "uv==" not in runtime and "uv==" not in internal


@pytest.mark.parametrize("path", [*dependencies.INPUTS, "requirements/runtime.txt"])
def test_stale_inputs_or_changed_locks_fail_before_install(locked_root, path, monkeypatch):
    (locked_root / path).write_text("# changed\n")
    calls = []
    monkeypatch.setattr(dependencies.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValueError, match="inputs or locks changed"):
        dependencies.install(locked_root, "runtime")
    assert calls == []


@pytest.mark.parametrize("profile", dependencies.PROFILES)
def test_installer_hashes_wheels_disables_hidden_resolution_and_checks_result(
    locked_root, profile, monkeypatch
):
    calls = []
    monkeypatch.setattr(dependencies.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    dependencies.install(locked_root, profile)
    commands = [args[0] for args, _ in calls]
    assert commands[0][3:] == [
        "install",
        "--require-hashes",
        "--only-binary=:all:",
        "-r",
        f"requirements/{profile}.txt",
    ]
    assert "--no-deps" in commands[1] and "--no-build-isolation" in commands[1]
    assert ("--editable" in commands[1]) is (profile == "dev")
    assert commands[1][-1] == ("." if profile == "runtime" else f".[{profile}]")
    assert commands[2][3:] == ["check"]
    assert all(kwargs == {"cwd": locked_root, "check": True} for _, kwargs in calls)


def test_invalid_profile_and_missing_manifest_fail_closed(locked_root):
    with pytest.raises(ValueError, match="Unsupported"):
        dependencies.install(locked_root, "unknown")
    (locked_root / dependencies.MANIFEST).unlink()
    with pytest.raises(FileNotFoundError):
        dependencies.check(locked_root)


@pytest.mark.parametrize("upgrade", [False, True])
def test_lock_compiler_is_pinned_and_shared_versions_follow_dev(locked_root, monkeypatch, upgrade):
    calls = []
    monkeypatch.setattr(dependencies.shutil, "which", lambda _: "/tools/uv")

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=f"uv {dependencies.COMPILER_VERSION} (test)\n")

    monkeypatch.setattr(dependencies.subprocess, "run", run)
    dependencies.generate(locked_root, upgrade=upgrade)
    assert calls[0] == ["/tools/uv", "--version"]
    assert ("--upgrade" in calls[1]) is upgrade
    for command in calls[1:]:
        assert "--universal" in command and "--generate-hashes" in command
        assert command[command.index("--python-version") + 1] == "3.11"
    dev_command = calls[1][:-1] if upgrade else calls[1]
    assert dev_command[-2:] == ["--extra", "dev"]
    assert calls[2][-2:] == ["--constraint", "requirements/dev.txt"]
    assert calls[3][-4:] == ["--constraint", "requirements/dev.txt", "--extra", "internal"]
    dependencies.check(locked_root)


def test_missing_or_wrong_compiler_is_rejected(locked_root, monkeypatch):
    monkeypatch.setattr(dependencies.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="compiler first"):
        dependencies.generate(locked_root)
    monkeypatch.setattr(dependencies.shutil, "which", lambda _: "/tools/uv")
    monkeypatch.setattr(dependencies.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="uv 0.0.1"))
    with pytest.raises(ValueError, match="requires uv"):
        dependencies.generate(locked_root)


def test_failed_install_does_not_attempt_local_project(locked_root, monkeypatch):
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(dependencies.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        dependencies.install(locked_root, "runtime")
    assert len(calls) == 1


@pytest.mark.parametrize("command", [["check"], ["lock", "--upgrade"], ["install", "internal"]])
def test_dependency_cli_dispatches_success(locked_root, monkeypatch, command, capsys):
    calls = []
    monkeypatch.setattr(dependencies, "ROOT", locked_root)
    monkeypatch.setattr(dependencies.sys, "argv", ["dependencies.py", *command])
    monkeypatch.setattr(dependencies, "generate", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(dependencies, "install", lambda *a, **kw: calls.append((a, kw)))
    assert dependencies.main() == 0
    assert "completed" in capsys.readouterr().out
    if command[0] == "lock":
        assert calls == [((locked_root,), {"upgrade": True})]
    elif command[0] == "install":
        assert calls == [((locked_root, "internal"), {})]


@pytest.mark.parametrize("content", ["{}", "invalid json"])
def test_dependency_cli_reports_invalid_manifest(locked_root, monkeypatch, capsys, content):
    (locked_root / dependencies.MANIFEST).write_text(content)
    monkeypatch.setattr(dependencies, "ROOT", locked_root)
    monkeypatch.setattr(dependencies.sys, "argv", ["dependencies.py", "check"])
    assert dependencies.main() == 1
    assert "Dependency check failed" in capsys.readouterr().err


def test_failed_generation_does_not_recertify_partial_locks(locked_root, monkeypatch):
    original_manifest = (locked_root / dependencies.MANIFEST).read_bytes()
    monkeypatch.setattr(dependencies.shutil, "which", lambda _: "/tools/uv")

    def run(command, **kwargs):
        if "--version" in command:
            return SimpleNamespace(stdout=f"uv {dependencies.COMPILER_VERSION}")
        (locked_root / "requirements/dev.txt").write_text("# partial update\n")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(dependencies.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        dependencies.generate(locked_root)
    assert (locked_root / dependencies.MANIFEST).read_bytes() == original_manifest
    with pytest.raises(ValueError):
        dependencies.check(locked_root)


@pytest.mark.parametrize(
    "reference",
    ["actions/checkout@v4", "actions/checkout@main", "actions/checkout@123abcd", "docker://alpine:latest", 5],
)
def test_mutable_or_invalid_action_reference_rejected(reference):
    with pytest.raises(ValueError):
        validate_workflows.validate_action_pins({"job": {"steps": [{"uses": reference}]}})


@pytest.mark.parametrize(
    "reference",
    [
        "actions/checkout@" + "a" * 40,
        "org/repo/.github/workflows/test.yml@" + "b" * 40,
        "docker://alpine@sha256:" + "c" * 64,
        "./.github/actions/local",
    ],
)
def test_immutable_and_local_action_references_accepted(reference):
    validate_workflows.validate_action_pins({"job": {"uses": reference, "steps": [{"run": "true"}]}})


def test_repository_workflows_pass_pinning_gate():
    assert validate_workflows.main() == 0


@pytest.mark.parametrize("content", [None, "jobs: [", "on: push\njobs: {}", "- not-a-workflow"])
def test_missing_malformed_or_invalid_workflows_fail(tmp_path, monkeypatch, capsys, content):
    monkeypatch.setattr(validate_workflows, "__file__", str(tmp_path / "scripts/validate_workflows.py"))
    directory = tmp_path / ".github/workflows"
    directory.mkdir(parents=True)
    if content is not None:
        (directory / "test.yaml").write_text(content)
    assert validate_workflows.main() == 1
    assert capsys.readouterr().err
