#!/usr/bin/env python3
"""List pending takes in the benchmark-audio container without ingesting.

Emits pending-contributions.json with one entry per pending .webm blob,
including the companion .meta.json fields and computed quality_flags.
The intranet review dashboard reads this via wwwCleansheet's catalog
builder.

Usage:
  python tools/scan-pending.py [--output PATH]
    --output PATH  Where to write pending-contributions.json
                   (default: <repo-root>/pending-contributions.json)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

STORAGE_ACCOUNT = "storageb681"
CONTAINER = "benchmark-audio"
BLOB_PREFIX = "contributions/"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "pending-contributions.json"


def run_az(*args: str) -> str:
    result = subprocess.run(["az", *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"az error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def fetch_meta(blob_name: str, tmpdir: str) -> dict | None:
    dest = os.path.join(tmpdir, f"meta-{os.urandom(4).hex()}.json")
    result = subprocess.run(
        ["az", "storage", "blob", "download",
         "--container-name", CONTAINER,
         "--account-name", STORAGE_ACCOUNT,
         "--name", blob_name,
         "--file", dest,
         "--output", "none"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        with open(dest) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def compute_flags(meta: dict | None, duration: float | None) -> list[str]:
    flags: list[str] = []
    if meta is None:
        flags.append("missing-meta")
    if duration is not None:
        if duration < 10:
            flags.append("short-take")
        elif duration > 600:
            flags.append("long-take")
    if meta:
        mic = (meta.get("micLabel") or "").strip().lower()
        if not mic or mic in ("default", "unknown"):
            flags.append("unknown-mic")
    return flags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    raw = run_az(
        "storage", "blob", "list",
        "--container-name", CONTAINER,
        "--prefix", BLOB_PREFIX,
        "--account-name", STORAGE_ACCOUNT,
        "--output", "json",
    )
    blobs = json.loads(raw)

    # Group by lang/transcriptId/stem to pair webm with meta.json
    webm_blobs: list[dict] = []
    meta_blobs: dict[tuple[str, str, str], str] = {}
    for blob in blobs:
        name = blob["name"]
        parts = name.removeprefix(BLOB_PREFIX).split("/")
        if len(parts) != 3:
            continue
        lang, tid, filename = parts
        size = blob.get("properties", {}).get("contentLength", 0)
        date = blob.get("properties", {}).get("lastModified", "")
        if filename.endswith(".webm"):
            stem = filename[: -len(".webm")]
            webm_blobs.append({
                "lang": lang, "transcript_id": tid, "stem": stem,
                "blob_name": name, "size": size, "date": date,
            })
        elif filename.endswith(".meta.json"):
            stem = filename[: -len(".meta.json")]
            meta_blobs[(lang, tid, stem)] = name

    pending = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for wb in sorted(webm_blobs, key=lambda b: b["date"]):
            key = (wb["lang"], wb["transcript_id"], wb["stem"])
            meta_name = meta_blobs.get(key)
            meta = fetch_meta(meta_name, tmpdir) if meta_name else None
            duration = (meta or {}).get("durationSeconds")
            flags = compute_flags(meta, duration)
            pending.append({
                "lang": wb["lang"],
                "transcript_id": wb["transcript_id"],
                "blob_name": wb["blob_name"],
                "meta_blob_name": meta_name,
                "size_bytes": wb["size"],
                "submitted_at": (meta or {}).get("timestamp") or wb["date"],
                "contributor": (meta or {}).get("contributor"),
                "dialect": (meta or {}).get("dialect"),
                "mic_label": (meta or {}).get("micLabel"),
                "noise_condition": (meta or {}).get("noiseCondition"),
                "duration_seconds": duration,
                "quality_flags": flags,
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(pending, f, indent=2)
        f.write("\n")
    print(f"Wrote {len(pending)} pending take(s) to {args.output}")


if __name__ == "__main__":
    main()
