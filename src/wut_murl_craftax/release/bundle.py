"""Stage the Hugging Face dataset and Space from the local outputs, with a manifest."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from wut_murl_craftax.release.cards import (
    NOTICE,
    dataset_card,
    model_card,
    space_card,
    write_text,
)
from wut_murl_craftax.release.scrub import PATH_MARKS, scrub_store

ROOT = Path(__file__).resolve().parents[3]
SPACE_SRC = Path(__file__).parent / "space"
FINAL_PHASES = ("final-1m", "final-1b", "combo-1m", "combo-1b")
SKIP_DIRS = {"ckpt", "state"}
SKIP_SUFFIXES = {".mkv", ".pkl", ".wav", ".logged"}
SPACE_FIGURES = {  # name in the Space -> (figure folder, file)
    "legend.png": ("1m", "legend_methods.png"),
    "1m_aggregate.png": ("1m", "aggregate.png"),
    "1m_curves_main.png": ("1m", "curves_score_main.png"),
    "1m_curves_skills.png": ("1m", "curves_score_skills.png"),
    "1m_advanced.png": ("1m", "advanced_final.png"),
    "1m_deaths.png": ("1m", "deaths.png"),
    "1m_fidelity.png": ("1m", "fidelity_vs_leaves.png"),
    "1b_aggregate.png": ("1b", "aggregate.png"),
    "1b_curves_main.png": ("1b", "curves_score_main.png"),
    "1b_curves_skills.png": ("1b", "curves_score_skills.png"),
    "scale_scores.png": ("scale", "scale_scores.png"),
    "scale_advantage.png": ("scale", "scale_advantage.png"),
    "scale_speed.png": ("scale", "scale_speed.png"),
}
SPACE_TABLES = {  # name in the Space -> (budget folder, file)
    "1m_main.csv": ("1m", "main.csv"),
    "1b_main.csv": ("1b", "main.csv"),
    "literature.csv": ("1m", "literature.csv"),
    "game_summary.csv": ("1m", "game_summary.csv"),
}
OUTPUT_DIRS = (
    "metrics",
    "results",
    "analysis",
    "interpretation",
)  # outputs/<x> -> <x>/


def link(src: Path, dst: Path) -> None:
    """Hard link where possible (the staged copy costs no disk), else copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def stage_tree(src: Path, dst: Path) -> None:
    """Link the publishable files of `src` into `dst`."""
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if (
            p.is_file()
            and not SKIP_DIRS & set(rel.parts)
            and p.suffix not in SKIP_SUFFIXES
        ):
            link(p, dst / rel)


def write_manifest(out: Path) -> list[dict[str, Any]]:
    """`manifest.json`: path, size and SHA-256 of every file except itself."""
    entries = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h = hashlib.sha256()
            with p.open("rb") as f:
                while chunk := f.read(1 << 24):
                    h.update(chunk)
            entries.append({
                "path": p.relative_to(out).as_posix(),
                "size": p.stat().st_size,
                "sha256": h.hexdigest(),
            })
    (out / "manifest.json").write_text(json.dumps(entries, indent=1))
    return entries


def find_leaks(out: Path, limit: int = 50_000_000) -> list[str]:
    """Text files (json, csv, txt, md) that name an absolute home path."""
    pattern = re.compile("|".join(re.escape(m) for m in PATH_MARKS))
    texts = [
        p
        for p in sorted(out.rglob("*"))
        if p.suffix in {".json", ".csv", ".txt", ".md"}
        and p.is_file()
        and p.stat().st_size < limit
    ]
    return [
        p.relative_to(out).as_posix()
        for p in texts
        if pattern.search(p.read_text(errors="ignore"))
    ]


def final_runs(store: Path) -> list[dict[str, str]]:
    """Runs of the final phases with their method, budget and seed tags."""
    keys = ("method", "budget", "seed")
    cols = ",".join(
        f"(select value from tags where run_uuid=r.run_uuid and key='{k}')"  # nosec B608 - constant keys
        for k in keys
    )
    marks = ",".join("?" * len(FINAL_PHASES))
    sql = (
        f"select r.run_uuid, e.name, {cols} from runs r "  # nosec B608 - constants
        "join experiments e using (experiment_id) "
        f"where e.name in ({marks})"
    )
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as con:
        rows = con.execute(sql, FINAL_PHASES).fetchall()
    return [dict(zip(("run", "phase", *keys), r, strict=True)) for r in rows]


def stage_checkpoints(root: Path, out: Path, store: Path) -> None:
    """Last checkpoint of each final run: `checkpoints/<budget>/<method>/s<seed>/`."""
    for run in final_runs(store):
        art = root / "mlruns" / run["phase"] / run["run"] / "artifacts"
        ckpts = sorted(art.glob("ckpt/[0-9]*.msgpack"), key=lambda p: int(p.stem))
        if not ckpts:
            continue
        dst = out / "checkpoints" / run["budget"] / run["method"] / f"s{run['seed']}"
        link(ckpts[-1], dst / "final.msgpack")
        if (art / "config.json").is_file():
            link(art / "config.json", dst / "config.json")
        write_text(dst / "README.md", model_card(run))


def top_sizes(out: Path) -> dict[str, int]:
    """Bytes per top-level folder (`name/`) or file (`name`)."""
    sizes: dict[str, int] = {}
    for p in out.rglob("*"):
        if p.is_file():
            parts = p.relative_to(out).parts
            key = parts[0] + "/" if len(parts) > 1 else parts[0]
            sizes[key] = sizes.get(key, 0) + p.stat().st_size
    return sizes


def stage_dataset(
    root: Path, out: Path, store: Path, commit: str
) -> list[dict[str, Any]]:
    """Stage `out` (hard links) from `root` and the scrubbed `store`; manifest back."""
    link(store, out / "mlruns.db")
    stage_tree(root / "mlruns", out / "mlruns")
    for name in OUTPUT_DIRS:
        if (root / "outputs" / name).is_dir():
            stage_tree(root / "outputs" / name, out / name)
    vis = root / "outputs" / "visualisation"
    for sub, dst in (("gifs", "media/gifs"), ("out", "media/videos")):
        if (vis / sub).is_dir():
            stage_tree(vis / sub, out / dst)
    stage_checkpoints(root, out, store)
    for name in ("LICENSE", "report/report.pdf"):
        if (root / name).is_file():
            link(root / name, out / name)
    write_text(out / "NOTICE", NOTICE)
    write_text(out / "README.md", dataset_card(top_sizes(out), commit))
    return write_manifest(out)


def stage_space(root: Path, out: Path) -> list[dict[str, Any]]:
    """The static Space: page, card and the tables, figures and GIFs it shows."""
    link(SPACE_SRC / "index.html", out / "index.html")
    write_text(out / "README.md", space_card())
    res = root / "outputs" / "results"
    for name, (budget, src) in SPACE_TABLES.items():
        link(res / "tables" / budget / src, out / "data" / "tables" / name)
    for name, (folder, src) in SPACE_FIGURES.items():
        link(res / "figures" / folder / src, out / "data" / "figures" / name)
    for g in sorted((root / "outputs" / "visualisation" / "gifs").glob("*.gif"))[:4]:
        link(g, out / "data" / "gifs" / g.name)
    return write_manifest(out)


def main() -> None:
    """CLI: scrub the store once, then stage the dataset and the Space."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "release")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    commit = subprocess.run(  # nosec B607 - git from PATH
        ["git", "-C", str(args.root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    args.out.mkdir(parents=True, exist_ok=True)
    store = args.out / "mlruns.db"
    if not store.exists():
        print(scrub_store(args.root / "mlruns.db", store))
    for sub in ("dataset", "space"):
        shutil.rmtree(args.out / sub, ignore_errors=True)
    stage_dataset(args.root, args.out / "dataset", store, commit)
    stage_space(args.root, args.out / "space")
    for sub in ("dataset", "space"):
        print(
            sub, {k: f"{v / 1e6:,.1f} MB" for k, v in top_sizes(args.out / sub).items()}
        )
        print("leaks:", find_leaks(args.out / sub) or "none")


if __name__ == "__main__":
    main()
