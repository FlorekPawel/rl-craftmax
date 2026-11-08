"""Tests for staging the dataset and the Space."""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pytest

from wut_murl_craftax.release.bundle import (
    SPACE_FIGURES,
    find_leaks,
    stage_dataset,
    stage_space,
    write_manifest,
)

COMMIT = "a0fb5c8"


def put(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    art = r / "mlruns/final-1m/run1/artifacts"
    for name in (
        "config.json",
        "metrics.npz",
        "eval/greedy/1.npz",
        "eval_tables/a.parquet",
    ):
        put(art / name)
    for name in ("00000.msgpack", "00007.msgpack", "00148.msgpack", "index.json"):
        put(art / "ckpt" / name, name)
    put(r / "mlruns/tune-coarse/run2/artifacts/state/s.npz")
    put(r / "mlruns/tune-coarse/run2/artifacts/metrics.npz")
    put(r / "outputs/metrics/run1/eval_0_greedy.parquet")
    put(r / "outputs/metrics/run1/eval_0_greedy.logged")
    put(r / "outputs/metrics_v1/run1/old.parquet")
    put(r / "outputs/results/tables/1m/main.csv", "method,score\nppo,1\nsil,2\n")
    put(r / "outputs/results/tables/1m/literature.csv")
    put(r / "outputs/results/tables/1m/game_summary.csv")
    put(r / "outputs/results/tables/1b/main.csv", "method,score\nppo,5\n")
    for folder, src in SPACE_FIGURES.values():
        put(r / f"outputs/results/figures/{folder}/{src}")
    put(r / "outputs/analysis/1m/cases.csv")
    put(r / "outputs/analysis/1m/clip.mkv")
    put(r / "outputs/analysis/1m/state.pkl")
    put(r / "outputs/interpretation/1m/ppo/rules.txt")
    put(r / "outputs/visualisation/out/long.mp4")
    put(r / "outputs/visualisation/gifs/c004.gif")
    put(r / "outputs/visualisation/audio_voice.wav")
    put(r / ".env", "TOKEN=secret")
    put(r / "LICENSE", "MIT License")
    put(r / "report/report.pdf")
    db = r / "release.db"
    with sqlite3.connect(db) as con:
        con.executescript(
            "create table experiments (experiment_id integer, name text);"
            "create table runs (run_uuid text, experiment_id integer);"
            "create table tags (key text, value text, run_uuid text);"
        )
        con.execute(
            "insert into experiments values (1, 'final-1m'), (2, 'tune-coarse')"
        )
        con.execute("insert into runs values ('run1', 1), ('run2', 2)")
        con.executemany(
            "insert into tags values (?, ?, 'run1')",
            [("method", "ppo"), ("budget", "1m"), ("seed", "3")],
        )
    return r


def files(d: Path) -> set[str]:
    return {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}


def test_dataset_holds_exactly_the_publishable_files(
    root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "dataset"
    stage_dataset(root, out, root / "release.db", COMMIT)
    got = files(out)
    assert {
        "README.md",
        "LICENSE",
        "NOTICE",
        "mlruns.db",
        "mlruns/final-1m/run1/artifacts/config.json",
        "mlruns/final-1m/run1/artifacts/eval/greedy/1.npz",
        "mlruns/tune-coarse/run2/artifacts/metrics.npz",
        "checkpoints/1m/ppo/s3/final.msgpack",
        "checkpoints/1m/ppo/s3/config.json",
        "checkpoints/1m/ppo/s3/README.md",
        "metrics/run1/eval_0_greedy.parquet",
        "results/tables/1m/main.csv",
        "analysis/1m/cases.csv",
        "interpretation/1m/ppo/rules.txt",
        "media/videos/long.mp4",
        "media/gifs/c004.gif",
        "report/report.pdf",
    } <= got
    assert (out / "checkpoints/1m/ppo/s3/final.msgpack").read_text() == "00148.msgpack"
    banned = (
        ".env",
        ".wav",
        ".mkv",
        ".pkl",
        ".logged",
        "ckpt/",
        "state/",
        "metrics_v1",
        "tune-coarse/run2/artifacts/ckpt",
    )
    assert not [f for f in got if any(b in f for b in banned)]


def test_manifest_lists_path_size_and_sha256(root: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    stage_dataset(root, out, root / "release.db", COMMIT)
    entries = {e["path"]: e for e in json.loads((out / "manifest.json").read_text())}
    assert "manifest.json" not in entries
    assert set(entries) == files(out) - {"manifest.json"}
    cfg = entries["checkpoints/1m/ppo/s3/config.json"]
    data = (out / cfg["path"]).read_bytes()
    assert cfg["size"] == len(data)
    assert cfg["sha256"] == hashlib.sha256(data).hexdigest()
    assert write_manifest(out) == list(entries.values())


def test_cards_carry_commit_licence_and_measured_sizes(
    root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "dataset"
    stage_dataset(root, out, root / "release.db", COMMIT)
    card = (out / "README.md").read_text()
    assert card.startswith("---\nlicense: mit\n")
    assert COMMIT in card
    assert "| `checkpoints/` |" in card
    assert "| `mlruns.db` |" in card
    model = (out / "checkpoints/1m/ppo/s3/README.md").read_text()
    assert "license: mit" in model.split("---")[1]
    assert "ppo" in model
    assert "serialization" in model


def test_space_is_static_and_ships_its_own_data(root: Path, tmp_path: Path) -> None:
    out = tmp_path / "space"
    stage_space(root, out)
    got = files(out)
    assert {
        "index.html",
        "README.md",
        "manifest.json",
        "data/tables/1m_main.csv",
        "data/tables/1b_main.csv",
        "data/tables/literature.csv",
        "data/tables/game_summary.csv",
        "data/gifs/c004.gif",
    } <= got
    assert {f"data/figures/{n}" for n in SPACE_FIGURES} <= got
    assert "sdk: static" in (out / "README.md").read_text()
    assert not [f for f in got if f.endswith((".py", ".txt"))]


def test_every_file_the_page_names_is_staged(root: Path, tmp_path: Path) -> None:
    out = tmp_path / "space"
    stage_space(root, out)
    html = (out / "index.html").read_text()
    names = set(re.findall(r"data/[\w./-]+\.(?:csv|png|gif|json)", html))
    assert names
    assert all((out / n).is_file() for n in names)
    assert {n for n in names if "/figures/" in n} == {
        f"data/figures/{n}" for n in SPACE_FIGURES
    }
    assert not re.search(
        r"(?:src|href)=[\"']https?://[^\"']*\.js", html
    )  # no CDN scripts


def test_find_leaks_reports_private_paths(tmp_path: Path) -> None:
    put(tmp_path / "a.json", '{"p": "/Users/someone/x"}')
    put(tmp_path / "b.json", "{}")
    assert find_leaks(tmp_path) == ["a.json"]
