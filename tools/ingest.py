#!/usr/bin/env python3
"""Interactive ingest of benchmark audio contributions from Azure Blob Storage.

Lists pending takes from the benchmark-audio container, lets the reviewer
preview each take's metadata, downloads accepted submissions, converts
WebM → M4A via ffmpeg, appends to the transcript's audio_files[] in
meta.json, and deletes the source blob from Azure on success.

Multiple takes per transcript are supported and expected. Each take lands
in audio/{lang}/{id}/{timestamp}_{randomId}.m4a (preserving the blob name)
and gets its own entry in audio_files.

Prerequisites:
  - az CLI (authenticated)
  - ffmpeg  (`brew install ffmpeg`)
  - Python 3.9+

Usage:
  python tools/ingest.py [--dry-run] [--yes]
    --dry-run  Print what would happen, change nothing locally or remotely.
    --yes      Auto-accept every take (skip the per-take prompt).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

STORAGE_ACCOUNT = "storageb681"
CONTAINER = "benchmark-audio"
BLOB_PREFIX = "contributions/"

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = REPO_ROOT / "audio"
ANNOTATIONS_DIR = REPO_ROOT / "annotations"


# ── helpers ──────────────────────────────────────────────────────────────────


def run_az(*args: str) -> str:
    """Run an az CLI command and return stdout."""
    cmd = ["az", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  az error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def try_az(*args: str) -> tuple[bool, str]:
    """Run an az command; return (success, stderr)."""
    cmd = ["az", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def check_prerequisites() -> None:
    if not shutil.which("az"):
        print("Error: az CLI not found. Install via https://aka.ms/InstallAzureCLI")
        sys.exit(1)
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found. Install with `brew install ffmpeg`")
        sys.exit(1)


def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds or 0), 60)
    return f"{int(seconds or 0)}s ({m}m {s:02d}s)"


def format_size(nbytes: int) -> str:
    if nbytes >= 1_000_000:
        return f"{nbytes / 1_000_000:.1f} MB"
    if nbytes >= 1_000:
        return f"{nbytes / 1_000:.1f} KB"
    return f"{nbytes} B"


# ── blob listing ─────────────────────────────────────────────────────────────


def list_contributions() -> list[dict]:
    """Group pending blobs by (lang, transcript_id)."""
    raw = run_az(
        "storage", "blob", "list",
        "--container-name", CONTAINER,
        "--prefix", BLOB_PREFIX,
        "--account-name", STORAGE_ACCOUNT,
        "--output", "json",
    )
    blobs = json.loads(raw)

    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "webm_blobs": [],
        "meta_blobs_by_stem": {},
    })
    for blob in blobs:
        name: str = blob["name"]
        parts = name.removeprefix(BLOB_PREFIX).split("/")
        if len(parts) != 3:
            continue
        lang, transcript_id, filename = parts
        key = (lang, transcript_id)
        groups[key]["lang"] = lang
        groups[key]["transcript_id"] = transcript_id
        size = blob.get("properties", {}).get("contentLength", 0)
        date = blob.get("properties", {}).get("lastModified", "")
        if filename.endswith(".webm"):
            stem = filename[: -len(".webm")]
            groups[key]["webm_blobs"].append({
                "blob_name": name,
                "filename": filename,
                "stem": stem,
                "size": size,
                "date": date,
            })
        elif filename.endswith(".meta.json"):
            stem = filename[: -len(".meta.json")]
            groups[key]["meta_blobs_by_stem"][stem] = {
                "blob_name": name,
                "filename": filename,
            }

    results = []
    for _, grp in sorted(groups.items()):
        if grp["webm_blobs"]:
            grp["webm_blobs"].sort(key=lambda b: b["date"])
            results.append(grp)
    return results


def fetch_metadata(blob_name: str, tmpdir: str) -> dict | None:
    dest = os.path.join(tmpdir, f"meta-{os.urandom(4).hex()}.json")
    ok, err = try_az(
        "storage", "blob", "download",
        "--container-name", CONTAINER,
        "--account-name", STORAGE_ACCOUNT,
        "--name", blob_name,
        "--file", dest,
        "--output", "none",
    )
    if not ok:
        return None
    try:
        with open(dest) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


# ── download & convert ───────────────────────────────────────────────────────


def download_webm(blob_name: str, dest: str) -> None:
    run_az(
        "storage", "blob", "download",
        "--container-name", CONTAINER,
        "--account-name", STORAGE_ACCOUNT,
        "--name", blob_name,
        "--file", dest,
        "--output", "none",
    )


def convert_webm_to_m4a(webm_path: str, m4a_path: str) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", webm_path, "-c:a", "aac", "-b:a", "128k", m4a_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ffmpeg error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


def delete_blob(blob_name: str) -> bool:
    ok, err = try_az(
        "storage", "blob", "delete",
        "--container-name", CONTAINER,
        "--account-name", STORAGE_ACCOUNT,
        "--name", blob_name,
        "--output", "none",
    )
    if not ok:
        print(f"  warning: could not delete blob {blob_name}: {err}", file=sys.stderr)
    return ok


# ── metadata update ──────────────────────────────────────────────────────────


def append_audio_entry(
    lang: str,
    transcript_id: str,
    entry: dict,
) -> tuple[bool, str]:
    """Append entry to audio_files[] in the meta.json. Returns (updated, reason)."""
    meta_path = ANNOTATIONS_DIR / lang / f"{transcript_id}.meta.json"
    if not meta_path.exists():
        return False, "meta-not-found"

    with open(meta_path) as f:
        meta = json.load(f)

    audio_files = meta.get("audio_files")
    if not isinstance(audio_files, list):
        audio_files = []

    # Idempotency: skip if source_blob already recorded
    src = entry.get("source_blob")
    if src and any(af.get("source_blob") == src for af in audio_files):
        return False, "already-recorded"

    audio_files.append(entry)
    meta["audio_files"] = audio_files
    meta.pop("audio_file", None)  # remove legacy field if present

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    return True, "appended"


# ── main ─────────────────────────────────────────────────────────────────────


def process_take(
    grp: dict,
    take: dict,
    tmpdir: str,
    dry_run: bool,
    auto_yes: bool,
) -> str:
    """Process a single take. Returns status string."""
    lang = grp["lang"]
    tid = grp["transcript_id"]
    stem = take["stem"]
    meta_blob = grp["meta_blobs_by_stem"].get(stem)

    metadata = fetch_metadata(meta_blob["blob_name"], tmpdir) if meta_blob else None

    print(f"  • {tid}/{take['filename']} ({format_size(take['size'])})")
    if metadata:
        print(f"      contributor : {metadata.get('contributor', 'unknown')}")
        print(f"      duration    : {format_duration(metadata.get('durationSeconds', 0))}")
        print(f"      mic         : {metadata.get('micLabel', 'unknown')}")
        print(f"      noise       : {metadata.get('noiseCondition', 'unknown')}")
        print(f"      dialect     : {metadata.get('dialect', 'unknown')}")
    else:
        print("      (no meta.json companion)")
    print(f"      submitted   : {take['date']}")

    # Output path mirrors blob name
    dest_rel = f"audio/{lang}/{tid}/{stem}.m4a"
    dest = REPO_ROOT / dest_rel
    if dest.exists():
        # Already on disk — check meta idempotency
        meta_path = ANNOTATIONS_DIR / lang / f"{tid}.meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                existing = json.load(f)
            if any(
                af.get("source_blob") == take["blob_name"]
                for af in (existing.get("audio_files") or [])
            ):
                print(f"      already ingested → deleting blob")
                if not dry_run:
                    delete_blob(take["blob_name"])
                    if meta_blob:
                        delete_blob(meta_blob["blob_name"])
                return "already-ingested"

    if not auto_yes:
        choice = input("      [A]ccept / [S]kip / [Q]uit? ").strip().lower()
        if choice == "q":
            return "quit"
        if choice != "a":
            print()
            return "skipped"

    if dry_run:
        print(f"      would write → {dest_rel}")
        print(f"      would delete blob: {take['blob_name']}")
        if meta_blob:
            print(f"      would delete blob: {meta_blob['blob_name']}")
        print()
        return "dry-run"

    # Download
    webm_dest = os.path.join(tmpdir, f"{stem}.webm")
    print("      downloading...", end=" ", flush=True)
    download_webm(take["blob_name"], webm_dest)
    print(f"done ({format_size(os.path.getsize(webm_dest))})")

    # Convert
    m4a_tmp = os.path.join(tmpdir, f"{stem}.m4a")
    print("      converting WebM → M4A...", end=" ", flush=True)
    convert_webm_to_m4a(webm_dest, m4a_tmp)
    print(f"done ({format_size(os.path.getsize(m4a_tmp))})")

    # Place in repo
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(m4a_tmp, dest)
    print(f"      saved → {dest_rel}")

    # Append meta entry
    entry = {
        "path": dest_rel,
        "contributor": (metadata or {}).get("contributor") or "anonymous",
        "dialect": (metadata or {}).get("dialect"),
        "mic_label": (metadata or {}).get("micLabel"),
        "noise_condition": (metadata or {}).get("noiseCondition"),
        "duration_seconds": (metadata or {}).get("durationSeconds"),
        "submitted_at": (metadata or {}).get("timestamp"),
        "source_blob": take["blob_name"],
        "verified": False,
    }
    updated, reason = append_audio_entry(lang, tid, entry)
    if updated:
        print(f"      annotations/{lang}/{tid}.meta.json updated")
        # Delete blobs only after on-disk write + meta update succeed
        delete_blob(take["blob_name"])
        if meta_blob:
            delete_blob(meta_blob["blob_name"])
        print(f"      blob deleted from Azure")
        print()
        return "ingested"
    else:
        print(f"      meta update: {reason}")
        if reason == "meta-not-found":
            print(f"      WARNING: no annotation for {tid} — audio saved on disk but NOT catalogued; blob retained for retry")
        else:
            print(f"      blob retained for retry")
        print()
        return "saved-but-uncatalogued"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="No local writes, no blob deletes")
    parser.add_argument("--yes", action="store_true", help="Auto-accept every take")
    args = parser.parse_args()

    check_prerequisites()

    print(f"\nScanning {CONTAINER}/{BLOB_PREFIX}...")
    contributions = list_contributions()

    if not contributions:
        print("No pending contributions found.\n")
        return

    total_takes = sum(len(c["webm_blobs"]) for c in contributions)
    print(f"Found {total_takes} take(s) across {len(contributions)} transcript(s)\n")

    counts: dict[str, int] = {}
    quit_requested = False

    with tempfile.TemporaryDirectory() as tmpdir:
        for grp in contributions:
            if quit_requested:
                break
            print(f"── {grp['transcript_id']} ({len(grp['webm_blobs'])} take(s)) ──")
            for take in grp["webm_blobs"]:
                status = process_take(grp, take, tmpdir, args.dry_run, args.yes)
                counts[status] = counts.get(status, 0) + 1
                if status == "quit":
                    quit_requested = True
                    break

    print("Summary:")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")

    ingested = counts.get("ingested", 0)
    if ingested > 0 and not args.dry_run:
        print("\nNext steps:")
        print("  - Review: play the new audio file(s)")
        print("  - Rebuild catalog: cd ../wwwCleansheet && node scripts/build-catalog.cjs")
        print("  - Commit & push")
    print()


if __name__ == "__main__":
    main()
