#!/usr/bin/env python3
"""Score a candidate FHIR extraction against ground truth.

Computes precision, recall, and F1 per resource type and overall.
Matching is based on code system + code (exact match).
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ScoreResult:
    resource_type: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


SCORABLE_TYPES = {
    "Condition", "MedicationStatement", "MedicationRequest",
    "Observation", "AllergyIntolerance", "Procedure",
    "ServiceRequest", "FamilyMemberHistory",
}


def extract_codes(bundle: dict) -> dict[str, set[str]]:
    """Extract (system, code) pairs per resource type from a bundle."""
    result: dict[str, set[str]] = {rt: set() for rt in SCORABLE_TYPES}

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        rt = resource.get("resourceType", "")
        if rt not in SCORABLE_TYPES:
            continue

        codes = set()

        # Primary code field varies by resource type
        code_fields = ["code", "medicationCodeableConcept"]
        for cf in code_fields:
            code_obj = resource.get(cf)
            if code_obj:
                for coding in code_obj.get("coding", []):
                    system = coding.get("system", "")
                    code = coding.get("code", "")
                    if system and code:
                        codes.add(f"{system}|{code}")

        # Observation components (e.g., BP systolic/diastolic)
        for component in resource.get("component", []):
            comp_code = component.get("code", {})
            for coding in comp_code.get("coding", []):
                system = coding.get("system", "")
                code = coding.get("code", "")
                if system and code:
                    codes.add(f"{system}|{code}")

        result[rt].update(codes)

    return result


def score(ground_truth: dict, candidate: dict) -> dict[str, ScoreResult]:
    """Score candidate against ground truth. Returns per-type ScoreResults."""
    gt_codes = extract_codes(ground_truth)
    cand_codes = extract_codes(candidate)

    results = {}
    for rt in SCORABLE_TYPES:
        gt = gt_codes[rt]
        cand = cand_codes[rt]
        tp = len(gt & cand)
        fp = len(cand - gt)
        fn = len(gt - cand)
        results[rt] = ScoreResult(
            resource_type=rt,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
        )

    return results


def print_results(results: dict[str, ScoreResult], fmt: str = "table"):
    """Print scoring results."""
    total_tp = sum(r.true_positives for r in results.values())
    total_fp = sum(r.false_positives for r in results.values())
    total_fn = sum(r.false_negatives for r in results.values())

    if fmt == "json":
        output = {}
        for rt, r in sorted(results.items()):
            if r.true_positives + r.false_positives + r.false_negatives == 0:
                continue
            output[rt] = {
                "precision": round(r.precision, 4),
                "recall": round(r.recall, 4),
                "f1": round(r.f1, 4),
                "tp": r.true_positives,
                "fp": r.false_positives,
                "fn": r.false_negatives,
            }
        p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        output["_overall"] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        }
        print(json.dumps(output, indent=2))
        return

    # Table format
    print(f"{'Resource Type':<25} {'Prec':>6} {'Rec':>6} {'F1':>6}  {'TP':>3} {'FP':>3} {'FN':>3}")
    print("-" * 65)
    for rt, r in sorted(results.items()):
        if r.true_positives + r.false_positives + r.false_negatives == 0:
            continue
        print(
            f"{rt:<25} {r.precision:>6.2%} {r.recall:>6.2%} {r.f1:>6.2%}"
            f"  {r.true_positives:>3} {r.false_positives:>3} {r.false_negatives:>3}"
        )
    print("-" * 65)
    p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
    print(
        f"{'OVERALL':<25} {p:>6.2%} {r:>6.2%} {f1:>6.2%}"
        f"  {total_tp:>3} {total_fp:>3} {total_fn:>3}"
    )


def main():
    if len(sys.argv) < 3:
        print("Usage: python score.py <ground_truth.json> <candidate.json> [--json]")
        sys.exit(1)

    gt_path = Path(sys.argv[1])
    cand_path = Path(sys.argv[2])
    fmt = "json" if "--json" in sys.argv else "table"

    with open(gt_path) as f:
        ground_truth = json.load(f)
    with open(cand_path) as f:
        candidate = json.load(f)

    results = score(ground_truth, candidate)
    print_results(results, fmt)


if __name__ == "__main__":
    main()
