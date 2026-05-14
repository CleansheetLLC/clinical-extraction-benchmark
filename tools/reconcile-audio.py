#!/usr/bin/env python3
"""Reconcile on-disk audio with metadata.

Scans every transcript in transcripts/{lang}/*.txt and ensures:
  1. A meta.json exists in annotations/{lang}/. If missing, a stub is created.
     The stub inherits workflow/difficulty/specialty/entity_counts/notes from
     the matching EN-language meta (matched by workflow + sequence number)
     when one exists, otherwise uses safe defaults.
  2. Every audio file under audio/{lang}/ that belongs to this transcript is
     registered in the meta's audio_files[]. Two sources are reconciled:
       - Flat orphan files (audio/{lang}/{id}.m4a) — moved into
         audio/{lang}/{id}/{id}-legacy.m4a, then registered.
       - Files already in the subdir (audio/{lang}/{id}/*.m4a) that aren't
         in audio_files — registered with metadata probed via ffprobe.

Idempotent: safe to run repeatedly. Reports actions taken.

Usage:
  python tools/reconcile-audio.py [--dry-run] [--no-git]
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
ANNOTATIONS_DIR = REPO_ROOT / "annotations"
AUDIO_DIR = REPO_ROOT / "audio"

ID_PATTERN = re.compile(r"^([a-z]{2})-([a-z_]+)-(\d{3})$")


def probe_duration(path: Path) -> float | None:
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
    dest.parent.mkdir(parents=True, exist_ok=True)
    if use_git:
        result = subprocess.run(
            ["git", "mv", str(src), str(dest)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
    shutil.move(str(src), str(dest))


def parse_id(transcript_id: str) -> tuple[str, str, str] | None:
    m = ID_PATTERN.match(transcript_id)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def load_en_counterparts() -> dict[str, dict]:
    """Build {workflow-seq: en_meta} from English meta files."""
    out: dict[str, dict] = {}
    en_dir = ANNOTATIONS_DIR / "en"
    if not en_dir.exists():
        return out
    for mp in en_dir.glob("*.meta.json"):
        with open(mp) as f:
            meta = json.load(f)
        tid = meta.get("id")
        if not tid:
            continue
        parsed = parse_id(tid)
        if not parsed:
            continue
        _, workflow, seq = parsed
        out[f"{workflow}-{seq}"] = meta
    return out


def stub_meta(transcript_id: str, lang: str, en_counterpart: dict | None) -> dict:
    parsed = parse_id(transcript_id)
    workflow = parsed[1] if parsed else "general"
    base = {
        "id": transcript_id,
        "language": lang,
        "workflow": workflow,
        "source": "original",
        "verified": False,
        "annotation_file": None,
        "specialty": [],
        "entity_counts": {},
        "annotators": [],
        "difficulty": "moderate",
        "notes": "",
        "audio_files": [],
    }
    if en_counterpart:
        for key in ("workflow", "specialty", "entity_counts", "difficulty", "notes"):
            if key in en_counterpart:
                base[key] = en_counterpart[key]
    return base


def reconcile_transcript(
    transcript_id: str,
    lang: str,
    en_counterparts: dict[str, dict],
    dry_run: bool,
    use_git: bool,
) -> list[str]:
    """Returns a list of action strings taken (or would take in dry-run)."""
    actions: list[str] = []
    meta_path = ANNOTATIONS_DIR / lang / f"{transcript_id}.meta.json"
    parsed = parse_id(transcript_id)
    en_key = f"{parsed[1]}-{parsed[2]}" if parsed else None
    en_counterpart = en_counterparts.get(en_key) if en_key else None

    # 1. Ensure meta.json exists
    if not meta_path.exists():
        actions.append(f"create-meta")
        if not dry_run:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(meta_path, "w") as f:
                json.dump(stub_meta(transcript_id, lang, en_counterpart), f, indent=2)
                f.write("\n")
        meta = stub_meta(transcript_id, lang, en_counterpart)
    else:
        with open(meta_path) as f:
            meta = json.load(f)
        if "audio_files" not in meta:
            meta["audio_files"] = []
            actions.append("init-audio-files")

    audio_files = meta.get("audio_files") or []
    existing_paths = {af.get("path") for af in audio_files}

    # 2. Handle flat orphan: audio/{lang}/{transcript_id}.m4a
    flat = AUDIO_DIR / lang / f"{transcript_id}.m4a"
    if flat.exists():
        dest_rel = f"audio/{lang}/{transcript_id}/{transcript_id}-legacy.m4a"
        dest = REPO_ROOT / dest_rel
        if dest.exists():
            # Subdir version already exists — drop the flat orphan
            actions.append(f"remove-duplicate-flat: {flat.relative_to(REPO_ROOT)}")
            if not dry_run:
                flat.unlink()
        else:
            actions.append(f"move-flat-to-subdir: {dest_rel}")
            if not dry_run:
                git_mv(flat, dest, use_git)
            if dest_rel not in existing_paths:
                audio_files.append({
                    "path": dest_rel,
                    "contributor": "unknown",
                    "dialect": None,
                    "mic_label": None,
                    "noise_condition": None,
                    "duration_seconds": probe_duration(dest if not dry_run else flat),
                    "submitted_at": None,
                    "source_blob": None,
                    "verified": True,
                })
                existing_paths.add(dest_rel)

    # 3. Scan subdir for orphan files not in audio_files
    subdir = AUDIO_DIR / lang / transcript_id
    if subdir.exists() and subdir.is_dir():
        for f in sorted(subdir.iterdir()):
            if not f.is_file() or not f.name.endswith(".m4a"):
                continue
            rel = f"audio/{lang}/{transcript_id}/{f.name}"
            if rel in existing_paths:
                continue
            actions.append(f"register-orphan: {rel}")
            stem = f.stem
            is_legacy = stem.endswith("-legacy")
            audio_files.append({
                "path": rel,
                "contributor": "unknown" if is_legacy else "anonymous",
                "dialect": None,
                "mic_label": None,
                "noise_condition": None,
                "duration_seconds": probe_duration(f),
                "submitted_at": None,
                "source_blob": None,
                "verified": is_legacy,
            })
            existing_paths.add(rel)

    # 4. Write meta back if we changed it
    if not dry_run and actions:
        meta["audio_files"] = audio_files
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
            f.write("\n")

    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-git", action="store_true")
    args = parser.parse_args()

    use_git = not args.no_git and (REPO_ROOT / ".git").exists()
    en_counterparts = load_en_counterparts()

    if not TRANSCRIPTS_DIR.exists():
        print(f"No transcripts dir at {TRANSCRIPTS_DIR}")
        sys.exit(1)

    counts: dict[str, int] = {}
    total = 0
    for lang_dir in sorted(TRANSCRIPTS_DIR.iterdir()):
        if not lang_dir.is_dir():
            continue
        lang = lang_dir.name
        for txt in sorted(lang_dir.glob("*.txt")):
            total += 1
            tid = txt.stem
            actions = reconcile_transcript(tid, lang, en_counterparts, args.dry_run, use_git)
            for a in actions:
                key = a.split(":", 1)[0]
                counts[key] = counts.get(key, 0) + 1
            if actions:
                print(f"  {lang}/{tid}: {', '.join(actions)}")

    print(f"\nScanned {total} transcripts (dry_run={args.dry_run})")
    print("Actions:")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    if not counts:
        print("  (no changes needed)")


if __name__ == "__main__":
    main()
