"""Tests for the publishable MLflow copy."""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from wut_murl_craftax.release.scrub import scrub_report, scrub_store

SCHEMA = """
create table experiments (experiment_id integer, name text, artifact_location text);
create table experiment_tags (key text, value text, experiment_id integer);
create table runs (run_uuid text, experiment_id integer, artifact_uri text);
create table tags (key text, value text, run_uuid text);
create table params (key text, value text, run_uuid text);
create table metrics (key text, value real, run_uuid text);
"""
TAGS = [
    ("mlflow.user", "pawel.pozorski"),
    ("mlflow.source.name", "/Users/pawel/x/queue.py"),
    ("host_name", "dgx-3"),
    ("note", "ran on dgx-3 overnight"),
    ("path_note", "/home/ppozorski/out"),
    ("mlflow.source.git.repoURL", "/Users/pawel/repo"),
    ("method", "ppo"),
    ("budget", "1m"),
    ("seed", "3"),
    ("mlflow.source.git.commit", "abc123"),
]


@pytest.fixture
def store(tmp_path: Path) -> Path:
    path = tmp_path / "mlruns.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        "insert into experiments values (1, 'final-1m', 'file:///Users/pawel/mlruns/final-1m')"
    )
    con.execute("insert into experiment_tags values ('k', '/Users/pawel', 1)")
    con.execute(
        "insert into runs values ('r1', 1, 'file:///Users/pawel/mlruns/final-1m/r1/artifacts')"
    )
    con.executemany("insert into tags values (?, ?, 'r1')", TAGS)
    con.execute("insert into params values ('lr', '0.1', 'r1')")
    con.executemany("insert into metrics values ('m', ?, 'r1')", [(1.0,), (2.0,)])
    con.commit()
    con.close()
    return path


def rows(path: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(path) as con:
        return con.execute(sql).fetchall()


def test_private_tags_go_and_allowed_tags_stay(store: Path, tmp_path: Path) -> None:
    dst = tmp_path / "out.db"
    scrub_store(store, dst)
    kept = {k for (k,) in rows(dst, "select key from tags")}
    assert kept == {"method", "budget", "seed", "mlflow.source.git.commit"}
    assert rows(dst, "select count(*) from experiment_tags") == [(0,)]


def test_artifact_locations_become_relative(store: Path, tmp_path: Path) -> None:
    dst = tmp_path / "out.db"
    scrub_store(store, dst)
    assert rows(dst, "select artifact_uri from runs") == [
        ("mlruns/final-1m/r1/artifacts",)
    ]
    assert rows(dst, "select artifact_location from experiments") == [
        ("mlruns/final-1m",)
    ]


def test_counts_match_and_the_source_is_untouched(store: Path, tmp_path: Path) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    dst = tmp_path / "out.db"
    report = scrub_store(store, dst)
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before
    assert report == scrub_report(store, dst)
    assert report["runs"] == (1, 1)
    assert report["metrics"] == (2, 2)
    assert report["params"] == (1, 1)
    assert report["tags"] == (10, 4)
    assert sorted(report["deleted_tag_keys"]) == sorted([
        "mlflow.user",
        "mlflow.source.name",
        "host_name",
        "note",
        "path_note",
        "mlflow.source.git.repoURL",
    ])
