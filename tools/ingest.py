#!/usr/bin/env python3
"""Interactive ingest of benchmark audio contributions from Azure Blob Storage.

Lists pending contributions from the benchmark-audio container, lets the
reviewer preview metadata, downloads accepted submissions, converts
WebM → M4A via ffmpeg, and updates the repo.

Prerequisites:
  - az CLI (authenticated)
  - ffmpeg  (`brew install ffmpeg`)
  - Python 3.9+

Usage:
  python tools/ingest.py
"""

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

# Resolve repo root (script lives in tools/)
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


def check_prerequisites() -> None:
    """Verify az and ffmpeg are available."""
    if not shutil.which("az"):
        print("Error: az CLI not found. Install via https://aka.ms/InstallAzureCLI")
        sys.exit(1)
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found. Install with:")
        print("  brew install ffmpeg")
        sys.exit(1)


def format_duration(seconds: float) -> str:
    """Format seconds as e.g. '172s (2m 52s)'."""
    m, s = divmod(int(seconds), 60)
    return f"{int(seconds)}s ({m}m {s:02d}s)"


def format_size(nbytes: int) -> str:
    """Format bytes as human-readable size."""
    if nbytes >= 1_000_000:
        return f"{nbytes / 1_000_000:.1f} MB"
    if nbytes >= 1_000:
        return f"{nbytes / 1_000:.1f} KB"
    return f"{nbytes} B"


# ── blob listing ─────────────────────────────────────────────────────────────


def list_contributions() -> list[dict]:
    """List contribution blobs grouped by transcript ID.

    Returns a list of dicts, each with:
      lang, transcript_id, webm_blobs [(name, size, date)], metadata
    """
    raw = run_az(
        "storage", "blob", "list",
        "--container-name", CONTAINER,
        "--prefix", BLOB_PREFIX,
        "--account-name", STORAGE_ACCOUNT,
        "--output", "json",
    )
    blobs = json.loads(raw)

    # Group by lang/transcriptId
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "webm_blobs": [],
        "meta_blobs": [],
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
            groups[key]["webm_blobs"].append({
                "blob_name": name,
                "filename": filename,
                "size": size,
                "date": date,
            })
        elif filename.endswith(".meta.json"):
            groups[key]["meta_blobs"].append({
                "blob_name": name,
                "filename": filename,
            })

    # Filter to groups that actually have a webm
    results = []
    for key, grp in sorted(groups.items()):
        if grp["webm_blobs"]:
            results.append(grp)
    return results


def fetch_metadata(blob_name: str, tmpdir: str) -> dict | None:
    """Download and parse a .meta.json blob."""
    dest = os.path.join(tmpdir, "meta.json")
    run_az(
        "storage", "blob", "download",
        "--container-name", CONTAINER,
        "--account-name", STORAGE_ACCOUNT,
        "--name", blob_name,
        "--file", dest,
        "--output", "none",
    )
    try:
        with open(dest) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


# ── download & convert ───────────────────────────────────────────────────────


def download_webm(blob_name: str, dest: str) -> None:
    """Download a webm blob to dest path."""
    run_az(
        "storage", "blob", "download",
        "--container-name", CONTAINER,
        "--account-name", STORAGE_ACCOUNT,
        "--name", blob_name,
        "--file", dest,
        "--output", "none",
    )


def convert_webm_to_m4a(webm_path: str, m4a_path: str) -> None:
    """Convert WebM/Opus to M4A/AAC via ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", webm_path, "-c:a", "aac", "-b:a", "128k", m4a_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ffmpeg error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


# ── metadata update ──────────────────────────────────────────────────────────


def update_meta_json(lang: str, transcript_id: str, audio_rel_path: str) -> bool:
    """Update the annotation meta.json with the audio_file path.

    Returns True if the file was updated, False if not found.
    """
    meta_path = ANNOTATIONS_DIR / lang / f"{transcript_id}.meta.json"
    if not meta_path.exists():
        return False
    with open(meta_path) as f:
        meta = json.load(f)
    meta["audio_file"] = audio_rel_path
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    return True


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    check_prerequisites()

    print("\nScanning contributions in benchmark-audio container...")
    contributions = list_contributions()

    if not contributions:
        print("No pending contributions found.")
        return

    print(f"\nFound {len(contributions)} pending contribution(s):\n")

    accepted = 0
    skipped = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, contrib in enumerate(contributions, 1):
            lang = contrib["lang"]
            tid = contrib["transcript_id"]

            # Fetch metadata for the first meta blob (if any)
            metadata = None
            if contrib["meta_blobs"]:
                metadata = fetch_metadata(contrib["meta_blobs"][0]["blob_name"], tmpdir)

            # Display contribution info
            print(f"  {i}. {tid}")
            if metadata:
                name = metadata.get("contributor", "Unknown")
                mic = metadata.get("micLabel", "Unknown")
                noise = metadata.get("noiseCondition", "unknown")
                duration = metadata.get("durationSeconds", 0)
                submitted = metadata.get("timestamp", "")
                print(f"     Contributor: {name}")
                print(f"     Duration: {format_duration(duration)}")
                print(f"     Mic: {mic}")
                print(f"     Noise: {noise}")
                if submitted:
                    print(f"     Submitted: {submitted}")
            else:
                print("     (no metadata available)")

            # Show webm blob(s)
            webm_blobs = sorted(contrib["webm_blobs"], key=lambda b: b["date"])
            for wb in webm_blobs:
                print(f"     Blob: {wb['blob_name']} ({format_size(wb['size'])})")
                print(f"     Date: {wb['date']}")

            # Check if audio already exists
            dest_m4a = AUDIO_DIR / lang / f"{tid}.m4a"
            if dest_m4a.exists():
                print(f"     *** Audio already exists: {dest_m4a.relative_to(REPO_ROOT)}")

            print()

            # If multiple webm blobs, let reviewer pick
            chosen_blob = webm_blobs[0]
            if len(webm_blobs) > 1:
                print(f"     Multiple takes found ({len(webm_blobs)}):")
                for j, wb in enumerate(webm_blobs, 1):
                    print(f"       {j}. {wb['filename']} ({format_size(wb['size'])}) — {wb['date']}")
                pick = input("     Which take? [1]: ").strip()
                idx = int(pick) - 1 if pick.isdigit() else 0
                idx = max(0, min(idx, len(webm_blobs) - 1))
                chosen_blob = webm_blobs[idx]

            # Prompt
            if dest_m4a.exists():
                choice = input("[A]ccept (overwrite) / [S]kip / [Q]uit? ").strip().lower()
            else:
                choice = input("[A]ccept / [S]kip / [Q]uit? ").strip().lower()

            if choice == "q":
                print("Quitting.")
                break
            if choice != "a":
                skipped += 1
                print()
                continue

            # Download
            webm_dest = os.path.join(tmpdir, f"{tid}.webm")
            print("Downloading...", end=" ", flush=True)
            download_webm(chosen_blob["blob_name"], webm_dest)
            dl_size = os.path.getsize(webm_dest)
            print(f"done ({format_size(dl_size)})")

            # Convert
            m4a_tmp = os.path.join(tmpdir, f"{tid}.m4a")
            print("Converting WebM → M4A...", end=" ", flush=True)
            convert_webm_to_m4a(webm_dest, m4a_tmp)
            conv_size = os.path.getsize(m4a_tmp)
            print(f"done ({format_size(conv_size)})")

            # Place in repo
            dest_m4a.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(m4a_tmp, dest_m4a)
            audio_rel = f"audio/{lang}/{tid}.m4a"
            print(f"Saved: {audio_rel}")

            # Update meta.json
            if update_meta_json(lang, tid, audio_rel):
                print(f"Updated: annotations/{lang}/{tid}.meta.json (audio_file → {audio_rel})")
            else:
                transcript_dir = REPO_ROOT / "transcripts" / lang
                if not (transcript_dir / f"{tid}.txt").exists() and not (transcript_dir / f"{tid}.md").exists():
                    print(f"Warning: no matching transcript found in transcripts/{lang}/")
                print(f"Warning: annotations/{lang}/{tid}.meta.json not found — skipping metadata update")

            accepted += 1
            print()

    print(f"\nIngest complete: {accepted} accepted, {skipped} skipped.\n")
    if accepted > 0:
        print("Next steps:")
        print("  - Review: play the new audio file(s)")
        print("  - Rebuild catalog: cd ../wwwCleansheet && node scripts/build-catalog.cjs")
        print("  - Commit & push")
        print()


if __name__ == "__main__":
    main()
