"""Run the daily refresh in an isolated worktree; only Git publication changes production."""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from live_db_backup import backup

AUTOMATION_TRAILER = "UseThisModel-Automation: daily-refresh-v1"
ALLOWED_REMOTES = {
    "git@github.com:gibranpulga/usethismodel.git",
    "https://github.com/gibranpulga/usethismodel.git",
}


def meaningful_data_changes(paths):
    return any(path in {"data/catalog.json", "data/pending-review.json"} for path in paths)


def retain(directory, days=30, count=30):
    files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = time.time() - days * 86400
    for index, path in enumerate(files):
        if index >= count or path.stat().st_mtime < cutoff:
            path.unlink()


class Runner:
    def __init__(self, root, dry_run=False):
        self.root = root.resolve()
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        self.work = self.state / "worktree"
        self.database = self.state / "staged.sqlite3"
        self.pending = self.state / "pending.json"
        self.report_dir = self.state / "reports" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}"
        self.phase = "preflight"
        self.dry_run = dry_run
        self.python = str(self.root / ".venv/bin/python")
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes")
        # Never inherit a production database location into tests or updater code.
        self.env["DATABASE_PATH"] = str(self.state / "test-app.sqlite3")

    def run(self, args, cwd=None, capture=False, timeout=1200):
        result = subprocess.run(
            args, cwd=cwd or self.repo, env=self.env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=timeout,
        )
        if not capture or result.returncode:
            # Source/network failures may contain URLs or credentials. Keep raw output private
            # to this process; curated updater reports provide the source-specific diagnostics.
            logging.info("Command completed during %s (exit %s)", self.phase, result.returncode)
        result.check_returncode()
        return result.stdout.rstrip()

    def git(self, *args, cwd=None):
        return self.run(["git", *args], cwd=cwd, capture=True)

    def checks(self):
        self.phase = "data validation"
        self.run([self.python, "-m", "app.data_update", "validate", "--database", str(self.database)], cwd=self.work)
        self.phase = "pytest"
        self.run([self.python, "-m", "pytest", "-q"], cwd=self.work)
        self.phase = "ruff"
        self.run([self.python, "-m", "ruff", "check", "."], cwd=self.work)

    def archive_reports(self):
        self.report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = self.work / "data/reports"
        if source.exists():
            # Preserve reports from this run, including untracked no-change reports.
            changed = self.git("status", "--porcelain", "--untracked-files=all", "--", "data/reports", cwd=self.work)
            for line in changed.splitlines():
                relative = line[3:]
                path = self.work / relative
                if path.is_file() and path.suffix in {".md", ".json"} and path.parent == source:
                    shutil.copy2(path, self.report_dir / path.name)

    def status_report(self, outcome, error=None):
        self.report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # No exception message, command output, source payload, URL, or credential is copied.
        details = f"# Daily refresh\n\nResult: {outcome}\n\nLast phase: {self.phase}\n"
        if error:
            details += f"\nFailure type: {type(error).__name__}\n\nInspect the private job log and source review report.\n"
        details += "\nThe scheduler did not write to the live database.\n"
        (self.report_dir / "status.md").write_text(details)

    def cleanup(self):
        if self.work.exists():
            self.archive_reports()
            self.git("worktree", "remove", "--force", str(self.work))
        for path in (self.database, self.pending):
            path.unlink(missing_ok=True)

    def publish(self, commit):
        if self.dry_run:
            raise RuntimeError("Dry run cannot publish a pending commit; run the normal job to retry")
        if self.git("rev-parse", "origin/main") != commit:
            self.git("merge-base", "--is-ancestor", "origin/main", commit)
            self.checks()
            if self.git("status", "--porcelain", cwd=self.work):
                raise RuntimeError("Validation modified the pending worktree")
            self.phase = "GitHub push"
            self.git("push", "origin", f"{commit}:refs/heads/main")
        self.git("merge", "--ff-only", commit)
        logging.info("Published %s; Coolify automatic deployment follows the GitHub push", commit)
        self.cleanup()

    def execute(self):
        if self.git("remote", "get-url", "origin") not in ALLOWED_REMOTES:
            raise RuntimeError("origin must be the public repository URL without embedded credentials")
        if self.git("branch", "--show-current") != "main":
            raise RuntimeError("Scheduler checkout must be on main")
        if self.git("status", "--porcelain"):
            raise RuntimeError("Scheduler checkout is dirty; refusing to discard local work")
        self.git("fetch", "--prune", "origin", "main")
        # Main is never committed locally; pending automation commits live in the worktree.
        self.git("merge-base", "--is-ancestor", "HEAD", "origin/main")
        self.git("merge", "--ff-only", "origin/main")
        if self.pending.exists():
            pending = json.loads(self.pending.read_text())
            commit = pending["commit"]
            if self.git("rev-parse", "HEAD", cwd=self.work) != commit:
                raise RuntimeError("Pending worktree does not match checkpoint")
            if AUTOMATION_TRAILER not in self.git("show", "-s", "--format=%B", commit):
                raise RuntimeError("Pending commit lacks automation provenance")
            paths = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
            if not paths or any(not path.startswith("data/") for path in paths):
                raise RuntimeError("Pending commit contains unexpected changes")
            self.publish(commit)
            return
        self.cleanup()
        self.git("worktree", "add", "--detach", str(self.work), "origin/main")
        try:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            self.phase = "live SQLite backup"
            backup_path = self.state / "backups" / f"{stamp}.sqlite3"
            backup(backup_path)
            retain(backup_path.parent)
            shutil.copy2(backup_path, self.database)
            args = [self.python, "-m", "app.data_update", "update", "--database", str(self.database), "--output-dir", "data"]
            if self.dry_run:
                args.append("--dry-run")
            self.phase = "source update"
            self.run(args, cwd=self.work)
            self.archive_reports()
            self.checks()
            if self.dry_run:
                logging.info("Dry run complete; no artifacts or commits")
                return
            self.git("add", "--", "data", cwd=self.work)
            paths = self.git("diff", "--cached", "--name-only", cwd=self.work).splitlines()
            if self.dry_run or not meaningful_data_changes(paths):
                logging.info("Dry run complete" if self.dry_run else "No catalog or review changes; no commit")
                return
            self.git(
                "-c", "user.name=UseThisModel updater", "-c", "user.email=usethismodel-updater@users.noreply.github.com",
                "commit", "-m", f"data: refresh catalog {stamp[:8]}\n\n{AUTOMATION_TRAILER}", cwd=self.work,
            )
            commit = self.git("rev-parse", "HEAD", cwd=self.work)
            checkpoint = self.pending.with_suffix(".tmp")
            checkpoint.write_text(json.dumps({"commit": commit}) + "\n")
            checkpoint.replace(self.pending)
            self.publish(commit)
        finally:
            if not self.pending.exists():
                self.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    logs = args.root / "state/logs"
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    retain(logs, count=90)
    path = logs / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}.log"
    handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=2)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    runner = Runner(args.root, args.dry_run)
    try:
        runner.execute()
    except Exception as error:
        try:
            runner.archive_reports()
        except Exception:
            logging.error("Could not archive source reports; writing the scheduler status report")
        runner.status_report("failed", error)
        logging.error("Daily update failed during %s (%s); live database was not modified", runner.phase, type(error).__name__)
        print(f"Daily update failed; inspect {path}", file=sys.stderr)
        return 1
    runner.status_report("dry run completed" if args.dry_run else "completed")
    logging.info("Daily update finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
