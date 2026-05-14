#!/usr/bin/env python3
"""Remove duplicate audio takes within each transcript.

For every meta.json, hash each registered audio file. When two or more
entries share the same hash, they are the same recording. Keep the entry
with the richest metadata; delete the rest (both the file and its
audio_files entry).

Metadata-richness ranking (higher = keep):
  - contributor known (not None/empty/'unknown') vs unknown
  - has mic_label, dialect, noise_condition, submitted_at, source_blob
  - filename without '-legacy' suffix
  - earlier submitted_at as tiebreaker

Idempotent. Supports --dry-run.

Usage:
  python tools/dedupe-audio.py [--dry-run] [--no-git]
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def metadata_score(entry: dict) -> tuple:
    """Higher tuple = better. Used to pick which duplicate to keep."""
    contributor = (entry.get("contributor") or "").strip().lower()
    has_real_contributor = bool(contributor) and contributor != "unknown" and contributor != "anonymous"
    is_anonymous_known = contributor == "anonymous"
    field_count = sum(
        1 for k in ("dialect", "mic_label", "noise_condition", "submitted_at", "source_blob")
        if entry.get(k)
    )
    not_legacy = not Path(entry.get("path", "")).stem.endswith("-legacy")
    # Tiebreaker: earlier submitted_at wins (so negate sort key)
    submitted = entry.get("submitted_at") or "9999"
    return (
        int(has_real_contributor),
        int(is_anonymous_known),
        field_count,
        int(not_legacy),
        # earlier date wins → invert by using negative-ish ordering via reverse string
        # but we want max() so we want higher = better; earlier date = larger negative
        # Use submitted as-is for tiebreak; lower lexicographic = earlier; flip sign by
        # subtracting from sentinel: hard to do with strings, so wrap in a tuple where
        # we negate via comparison key. Simplest: keep as None placeholder and resolve
        # ties manually below.
    )


def git_rm(path: Path, use_git: bool) -> None:
    if use_git:
        result = subprocess.run(
            ["git", "rm", "--quiet", str(path)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
    if path.exists():
        path.unlink()


def dedupe_meta(meta_path: Path, dry_run: bool, use_git: bool) -> tuple[int, int]:
    """Returns (groups_with_duplicates, files_removed)."""
    with open(meta_path) as f:
        meta = json.load(f)

    audio_files = meta.get("audio_files") or []
    if len(audio_files) < 2:
        return 0, 0

    # Hash each file (skip entries whose file is missing)
    by_hash: dict[str, list[int]] = {}
    for i, af in enumerate(audio_files):
        p = REPO_ROOT / af.get("path", "")
        if not p.exists():
            continue
        h = file_hash(p)
        by_hash.setdefault(h, []).append(i)

    dup_groups = 0
    removed = 0
    keep_mask = [True] * len(audio_files)
    files_to_delete: list[Path] = []

    for h, idxs in by_hash.items():
        if len(idxs) < 2:
            continue
        dup_groups += 1
        # Choose the keeper: highest score, then earliest submitted_at among ties
        scored = sorted(
            idxs,
            key=lambda i: (
                metadata_score(audio_files[i]),
                # earlier date is better — invert for max sort
                # use negative comparison by mapping None/missing to "zzzz"
                -ord(((audio_files[i].get("submitted_at") or "z")[0])),
            ),
            reverse=True,
        )
        keep = scored[0]
        for i in idxs:
            if i == keep:
                continue
            keep_mask[i] = False
            p = REPO_ROOT / audio_files[i]["path"]
            files_to_delete.append(p)
            removed += 1

    if removed == 0:
        return 0, 0

    new_audio_files = [af for af, keep in zip(audio_files, keep_mask) if keep]

    rel_meta = meta_path.relative_to(REPO_ROOT)
    print(f"  {rel_meta}: kept {len(new_audio_files)}, removed {removed}")
    for p in files_to_delete:
        print(f"    - {p.relative_to(REPO_ROOT)}")

    if not dry_run:
        meta["audio_files"] = new_audio_files
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
            f.write("\n")
        for p in files_to_delete:
            git_rm(p, use_git)
            # Try to remove the parent dir if it's now empty (other than .gitkeep)
            parent = p.parent
            try:
                remaining = [c for c in parent.iterdir() if c.name != ".gitkeep"]
                if not remaining:
                    parent.rmdir()
            except (OSError, FileNotFoundError):
                pass

    return dup_groups, removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-git", action="store_true")
    args = parser.parse_args()

    use_git = not args.no_git and (REPO_ROOT / ".git").exists()

    metas = sorted(ANNOTATIONS_DIR.rglob("*.meta.json"))
    total_groups = 0
    total_removed = 0
    for mp in metas:
        groups, removed = dedupe_meta(mp, args.dry_run, use_git)
        total_groups += groups
        total_removed += removed

    print(f"\nScanned {len(metas)} meta files (dry_run={args.dry_run})")
    print(f"Duplicate groups found: {total_groups}")
    print(f"Files removed: {total_removed}")


if __name__ == "__main__":
    main()
