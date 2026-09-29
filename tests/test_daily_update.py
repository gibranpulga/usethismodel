"""Operational guards that do not contact GitHub, Docker, or production."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def scheduler(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("daily_update", scripts / "daily_update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reports_alone_do_not_create_a_commit(scheduler):
    assert not scheduler.meaningful_data_changes(["data/reports/20260929-hash.md"])
    assert scheduler.meaningful_data_changes(["data/pending-review.json"])
    assert scheduler.meaningful_data_changes(["data/catalog.json"])


def test_unknown_remote_rejected_before_fetch(scheduler, tmp_path):
    runner = scheduler.Runner(tmp_path)
    runner.git = lambda *args, **kwargs: "https://token@example.test/repo.git"
    with pytest.raises(RuntimeError, match="without embedded credentials"):
        runner.execute()


def test_dry_run_never_retries_a_push(scheduler, tmp_path):
    runner = scheduler.Runner(tmp_path, dry_run=True)
    with pytest.raises(RuntimeError, match="cannot publish"):
        runner.publish("abc123")


def test_validation_failure_never_pushes(scheduler, tmp_path):
    runner = scheduler.Runner(tmp_path)
    calls = []

    def git(*args, **kwargs):
        calls.append(args)
        return "old-head" if args[0] == "rev-parse" else ""

    def fail_checks():
        raise subprocess.CalledProcessError(1, "pytest")

    runner.git = git
    runner.checks = fail_checks
    with pytest.raises(subprocess.CalledProcessError):
        runner.publish("new-head")
    assert not any(args[0] == "push" for args in calls)


def test_backup_refuses_ambiguous_live_containers(scheduler, monkeypatch):
    helper = sys.modules["live_db_backup"]

    def output(args, **kwargs):
        if args[1] == "ps":
            return "abc\ndef\n"
        return json.dumps([{
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "Mounts": [{"Name": helper.VOLUME, "Destination": "/data"}],
        }]).encode()

    monkeypatch.setattr(helper.subprocess, "check_output", output)
    with pytest.raises(RuntimeError, match="exactly one"):
        helper.live_container()


def test_failure_report_omits_exception_secrets(scheduler, tmp_path):
    runner = scheduler.Runner(tmp_path)
    runner.phase = "source update"
    runner.status_report("failed", RuntimeError("token=super-secret"))
    report = (runner.report_dir / "status.md").read_text()
    assert "source update" in report
    assert "RuntimeError" in report
    assert "super-secret" not in report


def test_report_archive_survives_no_commit(scheduler, tmp_path):
    runner = scheduler.Runner(tmp_path)
    source = runner.work / "data/reports/refresh.md"
    source.parent.mkdir(parents=True)
    source.write_text("No changes today")
    runner.git = lambda *args, **kwargs: "?? data/reports/refresh.md"
    runner.archive_reports()
    assert (runner.report_dir / "refresh.md").read_text() == "No changes today"


def test_deploy_secret_requires_private_permissions(scheduler, tmp_path):
    helper = sys.modules['trigger_deploy']
    path = tmp_path / 'coolify-deploy.json'
    path.write_text('{"token":"secret"}')
    path.chmod(0o644)
    with pytest.raises(ValueError, match='0600'):
        helper.trigger(path)


def test_deploy_credential_is_only_in_authorization_header(scheduler, tmp_path, monkeypatch):
    helper = sys.modules['trigger_deploy']
    path = tmp_path / 'coolify-deploy.json'
    path.write_text('{"token":"test-secret"}')
    path.chmod(0o600)
    seen = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"deployments":[{"deployment_uuid":"verified"}]}'

    def opened(request, **kwargs):
        seen.append(request)
        return Reply()

    monkeypatch.setattr(helper, 'urlopen', opened)
    assert helper.trigger(path) == 'verified'
    assert seen[0].get_header('Authorization') == 'Bearer test-secret'
    assert 'secret' not in seen[0].full_url
    assert json.loads(seen[0].data) == {'uuid': helper.APP, 'force': False}
