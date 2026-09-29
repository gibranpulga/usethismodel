"""Copy the live SQLite database through SQLite's online backup API, read-only."""

import argparse
import json
import os
import sqlite3
import subprocess
from pathlib import Path

APP = "ild8duzk51xnfcuyxtyclzpg"
VOLUME = f"{APP}-usethismodel-data"
REMOTE_BACKUP = r"""
import os, sqlite3, sys, tempfile
fd, path = tempfile.mkstemp(suffix='.sqlite3')
os.close(fd)
try:
    with sqlite3.connect('file:/data/usethismodel.sqlite3?mode=ro', uri=True, timeout=30) as source:
        source.execute('PRAGMA query_only=ON')
        with sqlite3.connect(path) as target:
            source.backup(target)
    with open(path, 'rb') as stream:
        while chunk := stream.read(1024 * 1024):
            sys.stdout.buffer.write(chunk)
finally:
    os.unlink(path)
"""


def live_container():
    ids = subprocess.check_output(
        ["docker", "ps", "--filter", f"name={APP}", "--format", "{{.ID}}"], text=True
    ).split()
    candidates = []
    for container in ids:
        details = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
        mounts = details.get("Mounts", [])
        if any(m.get("Name") == VOLUME and m.get("Destination") == "/data" for m in mounts):
            health = details["State"].get("Health", {}).get("Status", "healthy")
            if details["State"]["Running"] and health == "healthy":
                candidates.append(container)
    if len(candidates) != 1:
        raise RuntimeError("Expected exactly one healthy application container with the data volume")
    return candidates[0]


def backup(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            subprocess.run(
                ["docker", "exec", "--user", "10001", live_container(), "python", "-c", REMOTE_BACKUP],
                stdout=stream, check=True, timeout=180,
            )
        with sqlite3.connect(f"{temporary.resolve().as_uri()}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("Backup failed SQLite integrity check")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    backup(parser.parse_args().destination)
