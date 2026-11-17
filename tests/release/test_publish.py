"""Tests for publishing with a mocked HfApi: private, verified, then public."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from wut_murl_craftax.release import publish
from wut_murl_craftax.release.bundle import write_manifest

DATASET, SPACE = "Pawlo77/wut-murl-craftax-results", "Pawlo77/wut-murl-craftax"


def git_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@pytest.fixture
def out(tmp_path: Path) -> Path:
    for sub, files in {
        "dataset": {"big.bin": b"B" * 50, "README.md": b"card"},
        "space": {"app.py": b"x"},
    }.items():
        for name, data in files.items():
            (tmp_path / sub / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / sub / name).write_bytes(data)
        write_manifest(tmp_path / sub)
    return tmp_path


def remote(folder: Path, size_delta: int = 0) -> list[SimpleNamespace]:
    """RepoFile-like rows: LFS files carry a sha256, small files a git blob id."""
    rows = []
    for e in json.loads((folder / "manifest.json").read_text()):
        data = (folder / e["path"]).read_bytes()
        lfs = SimpleNamespace(sha256=e["sha256"]) if len(data) > 10 else None
        rows.append(
            SimpleNamespace(
                path=e["path"],
                size=e["size"] + size_delta,
                lfs=lfs,
                blob_id=git_oid(data),
            )
        )
    return rows


def fake_api(out: Path, size_delta: int = 0, user: str = "Pawlo77") -> MagicMock:
    api = MagicMock()
    api.whoami.return_value = {"name": user}
    api.list_repo_tree.side_effect = lambda repo_id, **kw: remote(
        out / ("dataset" if kw["repo_type"] == "dataset" else "space"), size_delta
    )
    return api


def test_default_is_a_dry_run_without_api_calls(out: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(publish, "get_api", lambda: pytest.fail("api used"))
    publish.main(["--out", str(out)])
    text = capsys.readouterr().out
    assert DATASET in text
    assert SPACE in text
    assert "private" in text
    assert "mit" in text.lower()


def test_no_login_exits_before_any_write(out: Path, monkeypatch) -> None:
    api = fake_api(out)
    api.whoami.side_effect = RuntimeError("no token")
    monkeypatch.setattr(publish, "get_api", lambda: api)
    with pytest.raises(SystemExit, match="hf auth login"):
        publish.main(["--out", str(out), "--upload"])
    api.create_repo.assert_not_called()


def test_wrong_account_exits(out: Path, monkeypatch) -> None:
    api = fake_api(out, user="someone")
    monkeypatch.setattr(publish, "get_api", lambda: api)
    with pytest.raises(SystemExit, match="Pawlo77"):
        publish.main(["--out", str(out), "--upload"])
    api.create_repo.assert_not_called()


def test_upload_is_private_verified_and_stays_private(out: Path, monkeypatch) -> None:
    api = fake_api(out)
    monkeypatch.setattr(publish, "get_api", lambda: api)
    publish.main(["--out", str(out), "--upload"])
    kinds = {c.kwargs["repo_type"]: c.kwargs for c in api.create_repo.call_args_list}
    assert all(k["private"] is True for k in kinds.values())
    assert kinds["space"]["space_sdk"] == "static"
    assert api.upload_large_folder.call_args.kwargs["repo_id"] == DATASET
    assert api.upload_folder.call_args.kwargs["repo_id"] == SPACE
    api.update_repo_settings.assert_not_called()


def test_make_public_follows_a_successful_verification(out: Path, monkeypatch) -> None:
    api = fake_api(out)
    monkeypatch.setattr(publish, "get_api", lambda: api)
    publish.main(["--out", str(out), "--upload", "--make-public"])
    pairs = {
        (c.kwargs["repo_id"], c.kwargs["repo_type"], c.kwargs["private"])
        for c in api.update_repo_settings.call_args_list
    }
    assert pairs == {(DATASET, "dataset", False), (SPACE, "space", False)}


def test_a_size_mismatch_fails_verification_and_blocks_public(
    out: Path, monkeypatch
) -> None:
    api = fake_api(out, size_delta=1)
    monkeypatch.setattr(publish, "get_api", lambda: api)
    with pytest.raises(SystemExit, match="size"):
        publish.main(["--out", str(out), "--upload", "--make-public"])
    api.update_repo_settings.assert_not_called()


def test_a_hash_mismatch_fails_verification(out: Path, monkeypatch) -> None:
    api = fake_api(out)
    rows = remote(out / "dataset")
    rows[0].lfs = SimpleNamespace(sha256="0" * 64)
    api.list_repo_tree.side_effect = lambda repo_id, **kw: (
        rows if kw["repo_type"] == "dataset" else remote(out / "space")
    )
    monkeypatch.setattr(publish, "get_api", lambda: api)
    with pytest.raises(SystemExit, match="hash"):
        publish.main(["--out", str(out), "--upload"])


def test_make_public_alone_verifies_first_and_creates_nothing(
    out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = fake_api(out)
    monkeypatch.setattr(publish, "get_api", lambda: api)
    publish.main(["--out", str(out), "--make-public"])
    api.create_repo.assert_not_called()
    api.upload_large_folder.assert_not_called()
    assert api.update_repo_settings.call_count == 2


def test_update_space_touches_only_the_space(
    out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = fake_api(out)
    monkeypatch.setattr(publish, "get_api", lambda: api)
    publish.main(["--out", str(out), "--update-space"])
    assert api.upload_folder.call_args.kwargs["repo_id"] == SPACE
    assert api.upload_folder.call_args.kwargs["delete_patterns"] == ["data/*"]
    api.create_repo.assert_not_called()
    api.upload_large_folder.assert_not_called()
    api.update_repo_settings.assert_not_called()
    assert [c.args[0] for c in api.list_repo_tree.call_args_list] == [SPACE]
