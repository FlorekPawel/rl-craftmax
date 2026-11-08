"""Publishable MLflow store copy: no user, host or local path, relative URIs."""

import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ALWAYS_DROP = ("mlflow.user", "mlflow.source.name", "host_name")
PATH_MARKS = ("/Users/", "/home/", "/mnt/", "C:\\")
COUNTED = ("runs", "metrics", "params", "tags")


def _counts(con: sqlite3.Connection) -> dict[str, int]:
    return {
        t: con.execute(f"select count(*) from {t}").fetchone()[0]  # nosec B608
        for t in COUNTED
    }


def _drop_clause(hosts: list[str]) -> tuple[str, list[str]]:
    """SQL deleting tags that name a private key, a host or an absolute path."""
    marks = [f"%{m}%" for m in (*PATH_MARKS, *hosts)]
    keys = ",".join("?" * len(ALWAYS_DROP))
    likes = " or ".join("value like ?" for _ in marks)
    return f"key in ({keys}) or {likes}", [*ALWAYS_DROP, *marks]


def scrub_store(src: Path, dst: Path) -> dict[str, Any]:
    """Copy `src` to `dst` and scrub the copy; return `scrub_report(src, dst)`."""
    shutil.copyfile(src, dst)
    with sqlite3.connect(dst) as con:
        hosts = [
            h
            for (h,) in con.execute(
                "select distinct value from tags where key='host_name'"
            )
        ]
        where, args = _drop_clause(hosts)
        con.execute(f"delete from tags where {where}", args)  # nosec B608
        con.execute(f"delete from experiment_tags where {where}", args)  # nosec B608
        con.execute("update experiments set artifact_location = 'mlruns/' || name")
        con.execute(
            "update runs set artifact_uri = 'mlruns/' || (select name from"
            " experiments e where e.experiment_id = runs.experiment_id)"
            " || '/' || run_uuid || '/artifacts'"
        )
    return scrub_report(src, dst)


def scrub_report(src: Path, dst: Path) -> dict[str, Any]:
    """Counts (before, after) per table and the tag keys that were deleted."""
    with (
        sqlite3.connect(f"file:{src}?mode=ro", uri=True) as a,
        sqlite3.connect(dst) as b,
    ):
        before, after = _counts(a), _counts(b)
        gone = {k for (k,) in a.execute("select distinct key from tags")} - {
            k for (k,) in b.execute("select distinct key from tags")
        }
    report: dict[str, Any] = {t: (before[t], after[t]) for t in COUNTED}
    report["deleted_tag_keys"] = sorted(gone)
    return report


if __name__ == "__main__":
    print(scrub_store(Path(sys.argv[1]), Path(sys.argv[2])))
