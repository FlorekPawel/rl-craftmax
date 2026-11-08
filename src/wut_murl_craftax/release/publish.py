"""Publish the staged dataset and Space: dry run, private upload, verify, public.

Uses the user's existing Hugging Face login (`hf auth login` or `HF_TOKEN`);
never takes a token.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from wut_murl_craftax.release.bundle import ROOT, top_sizes
from wut_murl_craftax.release.cards import DATASET_ID, SPACE_ID

if TYPE_CHECKING:
    from huggingface_hub import HfApi

USER = "Pawlo77"
NOT_LOGGED_IN = (
    "Not logged in to Hugging Face: run `hf auth login` (or export HF_TOKEN) "
    "yourself, then retry."
)
REPOS = (
    ("dataset", DATASET_ID, "dataset"),
    ("space", SPACE_ID, "space"),
)  # folder, id, type


def get_api() -> "HfApi":
    """The Hub client; huggingface_hub comes with the `release` extra."""
    from huggingface_hub import HfApi

    return HfApi()


def dry_run(out: Path) -> None:
    """Print what an upload would create; no Hub call."""
    print(
        "Dry run, nothing is uploaded. Repositories are created private; licence mit."
    )
    for folder, repo_id, kind in REPOS:
        manifest = json.loads((out / folder / "manifest.json").read_text())
        print(
            f"\n{kind} {repo_id}: {len(manifest)} files, "
            f"{sum(e['size'] for e in manifest) / 1e9:,.2f} GB"
        )
        for name, size in sorted(top_sizes(out / folder).items()):
            n = sum(e["path"].startswith(name) for e in manifest)
            print(f"  {name:<18} {n:>7} files {size / 1e6:>10,.1f} MB")


def fail(message: str, cause: Exception | None = None) -> NoReturn:
    """Exit with `message`."""
    raise SystemExit(message) from cause


def check_login(api: "HfApi") -> None:
    """Exit unless the existing login belongs to the release account."""
    try:
        name = api.whoami()["name"]
    except Exception as exc:
        fail(NOT_LOGGED_IN, exc)
    if name != USER:
        fail(f"Logged in as {name}, expected {USER}; nothing written.")


def upload(api: "HfApi", out: Path) -> None:
    """Create both repositories private and upload the staged folders."""
    for _folder, repo_id, kind in REPOS:
        extra = {"space_sdk": "static"} if kind == "space" else {}
        api.create_repo(
            repo_id=repo_id, repo_type=kind, private=True, exist_ok=True, **extra
        )
    api.upload_large_folder(
        repo_id=DATASET_ID, repo_type="dataset", folder_path=out / "dataset"
    )
    api.upload_folder(repo_id=SPACE_ID, repo_type="space", folder_path=out / "space")


def _git_oid(path: Path) -> str:
    h = hashlib.sha1(f"blob {path.stat().st_size}\0".encode(), usedforsecurity=False)
    with path.open("rb") as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def update_space(api: "HfApi", out: Path) -> None:
    """Replace the files of the existing Space; visibility is never touched."""
    api.upload_folder(
        repo_id=SPACE_ID,
        repo_type="space",
        folder_path=out / "space",
        delete_patterns=["data/*"],  # drop figures the page no longer uses
        commit_message="Update the Space",
    )


def verify(
    api: "HfApi", out: Path, repos: tuple[tuple[str, str, str], ...] = REPOS
) -> None:
    """Every manifest file is on the Hub with the same size and hash."""
    for folder, repo_id, kind in repos:
        remote: dict[str, Any] = {
            f.path: f
            for f in api.list_repo_tree(repo_id, repo_type=kind, recursive=True)
            if hasattr(f, "size")
        }
        for e in json.loads((out / folder / "manifest.json").read_text()):
            f = remote.get(e["path"])
            if f is None:
                fail(f"{repo_id}: {e['path']} is missing")
            if f.size != e["size"]:
                fail(f"{repo_id}: {e['path']} size {f.size} != {e['size']}")
            same = (
                f.lfs.sha256 == e["sha256"]
                if f.lfs
                else f.blob_id == _git_oid(out / folder / e["path"])
            )
            if not same:
                fail(f"{repo_id}: {e['path']} hash differs")
    print("verified: every manifest file matches")


def make_public(api: "HfApi") -> None:
    """Make both repositories public."""
    for _, repo_id, kind in REPOS:
        api.update_repo_settings(repo_id=repo_id, repo_type=kind, private=False)
        print(f"public: https://huggingface.co/{kind}s/{repo_id}")


def main(argv: list[str] | None = None) -> None:
    """CLI: dry run by default."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "release")
    ap.add_argument("--dry-run", action="store_true", help="the default")
    ap.add_argument(
        "--upload",
        action="store_true",
        help="create both repos private, upload, verify",
    )
    ap.add_argument(
        "--make-public",
        action="store_true",
        help="after a successful verification, make both public",
    )
    ap.add_argument(
        "--update-space",
        action="store_true",
        help="upload only the Space folder to the existing Space, then verify it",
    )
    args = ap.parse_args(argv)
    if args.update_space:
        api = get_api()
        check_login(api)
        update_space(api, args.out)
        return verify(api, args.out, REPOS[1:])
    if not (args.upload or args.make_public):
        return dry_run(args.out)
    api = get_api()
    check_login(api)
    if args.upload:
        upload(api, args.out)
    verify(api, args.out)
    if args.make_public:
        make_public(api)
    return None


if __name__ == "__main__":
    main()
