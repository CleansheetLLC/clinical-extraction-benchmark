#!/usr/bin/env python3
"""One-shot migration: flat audio files → per-transcript subdirectory + audio_files[] metadata.

Before:
  audio/en/en-soap-001.m4a
  annotations/en/en-soap-001.meta.json: { "audio_file": "audio/en/en-soap-001.m4a", ... }

After:
  audio/en/en-soap-001/en-soap-001-legacy.m4a
  annotations/en/en-soap-001.meta.json: { "audio_files": [{...}], ... }  (audio_file removed)

Idempotent: skips entries already migrated (audio_files present and non-empty).
Uses `git mv` when inside a git repo so history follows the move.

Usage:
  python tools/migrate-audio-layout.py [--dry-run] [--no-git]
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = REPO_ROOT / "audio"
ANNOTATIONS_DIR = REPO_ROOT / "annotations"


def probe_duration(path: Path) -> float | None:
    """Use ffprobe to get audio duration in seconds. Returns None if ffprobe unavailable."""
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def git_mv(src: Path, dest: Path, use_git: bool) -> None:
    """Move src to dest, preferring `git mv` when in a git repo."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if use_git:
        result = subprocess.run(
            ["git", "mv", str(src), str(dest)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        # Fall through to plain move if git mv fails (e.g., file untracked)
    shutil.move(str(src), str(dest))


def migrate_one(meta_path: Path, dry_run: bool, use_git: bool) -> str:
    """Migrate a single meta.json + its audio file. Returns status string."""
    with open(meta_path) as f:
        meta = json.load(f)

    # Already migrated?
    existing_files = meta.get("audio_files")
    if isinstance(existing_files, list) and len(existing_files) > 0:
        return "skip-already-migrated"

    transcript_id = meta.get("id") or meta_path.stem.replace(".meta", "")
    lang = meta.get("language")
    if not lang:
        return f"warn-no-language: {meta_path}"

    # Determine legacy audio path: from meta.audio_file, or probe the conventional location
    legacy_path = meta.get("audio_file")
    if not legacy_path:
        candidate = AUDIO_DIR / lang / f"{transcript_id}.m4a"
        if candidate.exists():
            legacy_path = str(candidate.relative_to(REPO_ROOT))

    if not legacy_path:
        # No audio anywhere — just ensure audio_files exists as empty array
        if "audio_files" not in meta:
            if not dry_run:
                meta["audio_files"] = []
                meta.pop("audio_file", None)
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=2)
                    f.write("\n")
            return "init-empty"
        return "skip-no-audio"

    src = REPO_ROOT / legacy_path
    if not src.exists():
        return f"warn-missing: {legacy_path}"

    dest_rel = f"audio/{lang}/{transcript_id}/{transcript_id}-legacy.m4a"
    dest = REPO_ROOT / dest_rel

    if dest.exists():
        return f"skip-dest-exists: {dest_rel}"

    duration = probe_duration(src)

    if dry_run:
        return f"would-move: {legacy_path} → {dest_rel}"

    git_mv(src, dest, use_git)

    meta["audio_files"] = [{
        "path": dest_rel,
        "contributor": "unknown",
        "dialect": None,
        "mic_label": None,
        "noise_condition": None,
        "duration_seconds": duration,
        "submitted_at": None,
        "source_blob": None,
        "verified": True,
    }]
    meta.pop("audio_file", None)

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    return f"migrated: {dest_rel}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing files")
    parser.add_argument("--no-git", action="store_true", help="Use plain mv instead of git mv")
    args = parser.parse_args()

    use_git = not args.no_git and (REPO_ROOT / ".git").exists()

    counts: dict[str, int] = {}
    meta_files = sorted(ANNOTATIONS_DIR.rglob("*.meta.json"))
    if not meta_files:
        print(f"No meta.json files found under {ANNOTATIONS_DIR}")
        sys.exit(0)

    print(f"Scanning {len(meta_files)} meta files (dry_run={args.dry_run}, git={use_git})\n")

    for mp in meta_files:
        status = migrate_one(mp, args.dry_run, use_git)
        key = status.split(":", 1)[0]
        counts[key] = counts.get(key, 0) + 1
        if not status.startswith("skip-"):
            print(f"  {mp.relative_to(REPO_ROOT)} — {status}")

    print("\nSummary:")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
