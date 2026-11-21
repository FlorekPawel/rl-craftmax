"""Helpers for the tooling script tests."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(cwd: Path, *args: str) -> None:
    """Run a quiet git command in ``cwd``."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )
