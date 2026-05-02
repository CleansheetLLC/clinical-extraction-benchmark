#!/usr/bin/env python3
"""Batch score candidate extractions against ground truth annotations.

Walks annotations/ directory, matches candidates by filename, and produces
aggregate scores.

Usage:
    python batch_score.py <candidates_dir> [--json] [--lang en]
"""

import json
import sys
from pathlib import Path

# Allow importing score module from same directory
sys.path.insert(0, str(Path(__file__).parent))
from score import score, ScoreResult, SCORABLE_TYPES

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"


def find_pairs(
    candidates_dir: Path, lang: str | None = None
) -> list[tuple[Path, Path]]:
    """Find (ground_truth, candidate) pairs by matching filenames."""
    pairs = []
    lang_dirs = [ANNOTATIONS_DIR / lang] if lang else ANNOTATIONS_DIR.iterdir()

    for lang_dir in lang_dirs:
        if not lang_dir.is_dir():
            continue
        for gt_file in sorted(lang_dir.glob("*.json")):
            if gt_file.name.endswith(".meta.json"):
                continue
            # Look for matching candidate
            cand_file = candidates_dir / gt_file.name
            if not cand_file.exists():
                # Try with lang subdirectory
                cand_file = candidates_dir / lang_dir.name / gt_file.name
            if cand_file.exists():
                pairs.append((gt_file, cand_file))

    return pairs


def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_score.py <candidates_dir> [--json] [--lang en]")
        sys.exit(1)

    candidates_dir = Path(sys.argv[1])
    fmt = "json" if "--json" in sys.argv else "table"
    lang = None
    if "--lang" in sys.argv:
        lang_idx = sys.argv.index("--lang") + 1
        if lang_idx < len(sys.argv):
            lang = sys.argv[lang_idx]

    pairs = find_pairs(candidates_dir, lang)
    if not pairs:
        print("No matching ground truth / candidate pairs found.")
        sys.exit(1)

    # Aggregate scores
    aggregate: dict[str, ScoreResult] = {
        rt: ScoreResult(resource_type=rt) for rt in SCORABLE_TYPES
    }
    per_file_results = []

    for gt_path, cand_path in pairs:
        with open(gt_path) as f:
            gt = json.load(f)
        with open(cand_path) as f:
            cand = json.load(f)

        results = score(gt, cand)
        file_tp = sum(r.true_positives for r in results.values())
        file_fp = sum(r.false_positives for r in results.values())
        file_fn = sum(r.false_negatives for r in results.values())
        p = file_tp / (file_tp + file_fp) if (file_tp + file_fp) > 0 else 0
        r = file_tp / (file_tp + file_fn) if (file_tp + file_fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0

        per_file_results.append({
            "file": gt_path.name,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
        })

        for rt, sr in results.items():
            aggregate[rt].true_positives += sr.true_positives
            aggregate[rt].false_positives += sr.false_positives
            aggregate[rt].false_negatives += sr.false_negatives

    if fmt == "json":
        output = {
            "files_scored": len(pairs),
            "per_file": per_file_results,
            "aggregate": {},
        }
        total_tp = sum(a.true_positives for a in aggregate.values())
        total_fp = sum(a.false_positives for a in aggregate.values())
        total_fn = sum(a.false_negatives for a in aggregate.values())
        for rt, a in sorted(aggregate.items()):
            if a.true_positives + a.false_positives + a.false_negatives == 0:
                continue
            output["aggregate"][rt] = {
                "precision": round(a.precision, 4),
                "recall": round(a.recall, 4),
                "f1": round(a.f1, 4),
                "tp": a.true_positives,
                "fp": a.false_positives,
                "fn": a.false_negatives,
            }
        p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        output["aggregate"]["_overall"] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Scored {len(pairs)} file(s)\n")
        print(f"{'File':<30} {'Prec':>6} {'Rec':>6} {'F1':>6}")
        print("-" * 52)
        for fr in per_file_results:
            print(
                f"{fr['file']:<30} {fr['precision']:>6.2%}"
                f" {fr['recall']:>6.2%} {fr['f1']:>6.2%}"
            )
        print()
        print("Aggregate by resource type:")
        print(f"{'Resource Type':<25} {'Prec':>6} {'Rec':>6} {'F1':>6}")
        print("-" * 46)
        for rt, a in sorted(aggregate.items()):
            if a.true_positives + a.false_positives + a.false_negatives == 0:
                continue
            print(f"{rt:<25} {a.precision:>6.2%} {a.recall:>6.2%} {a.f1:>6.2%}")


if __name__ == "__main__":
    main()
