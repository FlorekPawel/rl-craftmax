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


def scratch_repo(tmp: Path) -> Path:
    """Create a git repo under ``tmp`` holding a copy of the hook scripts."""
    repo = tmp / "repo"
    (repo / "scripts" / "hooks").mkdir(parents=True)
    for f in HOOKS.glob("*.sh"):
        shutil.copy2(f, repo / "scripts" / "hooks" / f.name)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo-kit"\nversion = "9.8.7"\n\n'
        '[tool.kit]\nname = "demo-kit"\n',
        encoding="utf-8",
    )
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "chore: base")
    return repo
