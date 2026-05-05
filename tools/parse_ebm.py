#!/usr/bin/env python3
"""
Parse the KBV Einheitlicher Bewertungsmaßstab (EBM) PDF into structured JSON.

Usage:
    python parse_ebm.py path/to/2026-2-ebm.pdf [-o output.json] [--validate] [--subset voice-to-fhir]

Requires: pdfplumber >= 0.11
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORIENTIERUNGSPUNKTWERT = 0.1274  # Q2 2026

# Header/footer patterns to strip from each page
HEADER_RE = re.compile(r"^KBV\n(?:Kassenärztliche Bundesvereinigung\n?)?", re.MULTILINE)
FOOTER_RE = re.compile(
    r"^Stand \d/\d{4},\s*erstellt am \d{2}\.\d{2}\.\d{4}\s+Seite \d+ von \d+$",
    re.MULTILINE,
)

# A line that starts a code definition: 5 digits + space + description text.
# Exclude false positives from exclusion-list wrap-arounds where the 5-digit
# code is followed by a comma, another code, or connectors/verbs.
CODE_DEF_RE = re.compile(
    r"^(\d{5})\s+"                         # 5-digit code at line start
    r"(?!"                                  # negative lookahead for false positives
    r"(?:bis|und|oder|nicht|ist|sind|wird|kann|setzt|erfolgt|weiterhin|durch)\s"
    r"|"
    r"(?:berechnungsfähig|zu berechnen|zu beachten)"
    r"|"
    r"\d{4,5}[,\s]"                         # another code number
    r")"
    r"(.+)",                                # capture the rest of the line
    re.MULTILINE,
)

# German number formatting: 1.059,87 € (dot=thousands, comma=decimal)
EURO_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€")
# Punkte are plain integers (no thousands separator in PDF)
PUNKTE_RE = re.compile(r"(\d+)\s+Punkte")
AGE_TIER_RE = re.compile(
    r"(bis zum vollendeten|ab Beginn des)\s+(.+?)"
    r"(?:Lebensjahr(?:es)?)",
)
EXCLUSION_RE = re.compile(
    r"ist\s+(?:(?:am Behandlungstag|im Behandlungsfall|im Arztgruppenfall)\s+)?"
    r"nicht\s+(?:neben\s+)?(?:den?\s+)?"
    r"Gebührenordnungsposition(?:en)?\s+(.+?)\s+berechnungsfähig",
)
ZUSCHLAG_RE = re.compile(
    r"Zuschlag\s+zu\s+.{0,120}?"
    r"Gebührenordnungsposition(?:en)?\s+(\d{5})",
    re.DOTALL,
)
CODE_RANGE_RE = re.compile(r"(\d{5})\s+bis\s+(\d{5})")
CODE_REF_RE = re.compile(r"\d{5}")

FREQUENCY_TERMS = [
    "einmal im Behandlungsfall",
    "einmal im Arztgruppenfall",
    "einmal im Krankheitsfall",
    "je Sitzung",
    "je Behandlungstag",
    "je vollendete 5 Minuten",
    "je vollendete 10 Minuten",
    "je vollendete 15 Minuten",
    "je Bein",
    "je Extremität",
]

# Chapter mapping — first two digits of code → chapter name
CHAPTERS: dict[str, str] = {
    "01": "Allgemeine Gebührenordnungspositionen",
    "02": "Allgemeine diagnostische und therapeutische Gebührenordnungspositionen",
    "03": "Hausärztlicher Versorgungsbereich",
    "04": "Versorgungsbereich der Kinder- und Jugendmedizin",
    "05": "Anästhesiologische Gebührenordnungspositionen",
    "06": "Augenärztliche Gebührenordnungspositionen",
    "07": "Chirurgische Gebührenordnungspositionen",
    "08": "Frauenheilkunde und Geburtshilfe",
    "09": "Hals-Nasen-Ohren-ärztliche Gebührenordnungspositionen",
    "10": "Hautärztliche Gebührenordnungspositionen",
    "11": "Humangenetische Gebührenordnungspositionen",
    "12": "Laboratoriumsmedizinische Gebührenordnungspositionen (Kapitel 12 Fachärzte)",
    "13": "Innere Medizin",
    "14": "Kinder- und Jugendpsychiatrische Gebührenordnungspositionen",
    "15": "Mund-, Kiefer- und Gesichtschirurgische Gebührenordnungspositionen",
    "16": "Neurologie und Neurochirurgie",
    "17": "Nuklearmedizinische Gebührenordnungspositionen",
    "18": "Orthopädische Gebührenordnungspositionen",
    "19": "Pathologische Gebührenordnungspositionen",
    "20": "Phoniatrische und Pädaudiologische Gebührenordnungspositionen",
    "21": "Psychiatrische und Psychotherapeutische Gebührenordnungspositionen",
    "22": "Psychosomatische und Psychotherapeutische Gebührenordnungspositionen",
    "23": "Psychotherapeutische Gebührenordnungspositionen",
    "24": "Radiologische Gebührenordnungspositionen",
    "25": "Strahlentherapeuten",
    "26": "Urologische Gebührenordnungspositionen",
    "27": "Physikalische und Rehabilitative Medizin",
    "30": "Spezielle Versorgungsbereiche",
    "31": "Ambulante Operationen und stationsersetzende Eingriffe",
    "32": "In-vitro-Diagnostik der Laboratoriumsmedizin",
    "33": "Ultraschalldiagnostik",
    "34": "Radiologie, CT, MRT",
    "35": "Psychotherapie-Richtlinie",
    "36": "Belegärztliche Operationen",
    "37": "Versorgung gemäß Anlage 27 und 30 BMV-Ä",
    "38": "Delegationsvereinbarung",
    "40": "Kostenpauschalen",
    "50": "Sonderbereiche",
    "51": "Ambulante spezialfachärztliche Versorgung (ASV)",
    "61": "Erprobungsverfahren gemäß § 137e SGB V",
    "86": "Onkologie-Vereinbarung (Anhang)",
    "88": "Kennziffern",
}

# ---------------------------------------------------------------------------
# PDF Text Extraction
# ---------------------------------------------------------------------------


def extract_text_with_pages(pdf_path: str, start_page: int = 18, end_page: int | None = None) -> list[tuple[int, str]]:
    """Extract cleaned text from each page. Returns list of (page_number, text)."""
    pages: list[tuple[int, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        if end_page is None:
            end_page = total
        for i in range(start_page - 1, min(end_page, total)):
            raw = pdf.pages[i].extract_text()
            if not raw:
                continue
            # Strip header and footer
            text = HEADER_RE.sub("", raw)
            text = FOOTER_RE.sub("", text)
            text = text.strip()
            if text:
                pages.append((i + 1, text))  # 1-indexed page numbers
    return pages


# ---------------------------------------------------------------------------
# Code Block Splitting
# ---------------------------------------------------------------------------


def split_into_code_blocks(pages: list[tuple[int, str]]) -> list[dict]:
    """
    Join all page text with page markers, then split into code blocks.
    Returns list of {"code": str, "first_line_rest": str, "body": str, "page": int}.
    """
    # Build one big text with page markers
    parts: list[str] = []
    page_markers: list[tuple[int, int]] = []  # (char_offset, page_number)
    offset = 0
    for page_num, text in pages:
        page_markers.append((offset, page_num))
        parts.append(text)
        offset += len(text) + 1  # +1 for the join newline

    full_text = "\n".join(parts)

    # Find all code definition starts
    matches = list(CODE_DEF_RE.finditer(full_text))
    if not matches:
        return []

    raw_blocks: list[dict] = []
    for i, m in enumerate(matches):
        code = m.group(1)
        first_line_rest = m.group(2)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[m.end():end]

        # Determine page number from markers
        page = 1
        for char_off, pnum in page_markers:
            if char_off <= start:
                page = pnum
            else:
                break

        raw_blocks.append({
            "code": code,
            "first_line_rest": first_line_rest.strip(),
            "body": body.strip(),
            "page": page,
        })

    # Post-processing: validate blocks and merge false splits back
    blocks: list[dict] = []
    for block in raw_blocks:
        first = block["first_line_rest"]
        body = block["body"]
        # A real code definition has meaningful content:
        # - description > 20 chars, OR
        # - contains Leistungsinhalt/euro/Punkte
        is_real = (
            len(first) >= 20
            or "Leistungsinhalt" in body
            or EURO_RE.search(first + "\n" + body[:200])
            or PUNKTE_RE.search(first + "\n" + body[:200])
        )
        if is_real:
            blocks.append(block)
        elif blocks:
            # Merge false split back into previous block's body
            blocks[-1]["body"] += "\n" + block["code"] + " " + first + "\n" + body

    return blocks


# ---------------------------------------------------------------------------
# Code Block Parsing
# ---------------------------------------------------------------------------


def parse_euro(text: str) -> float | None:
    """Extract first euro value from text (handles German formatting: 1.059,87)."""
    m = EURO_RE.search(text)
    if m:
        val = m.group(1).replace(".", "").replace(",", ".")
        return float(val)
    return None


def parse_punkte(text: str) -> int | None:
    """Extract first Punkte value from text."""
    m = PUNKTE_RE.search(text)
    if m:
        return int(m.group(1))
    return None


def parse_description(first_line_rest: str, body: str) -> str:
    """
    Extract the description from the code's first line and continuation.
    The description is the text before the first euro value or structured section.
    """
    # The first_line_rest may contain the description + euro at the end
    desc_parts = []

    # Remove trailing euro value from first line
    line = EURO_RE.sub("", first_line_rest).strip()
    desc_parts.append(line)

    # Check if body starts with continuation of description (before Punkte line)
    body_lines = body.split("\n")
    for bline in body_lines:
        stripped = bline.strip()
        # If the line is just Punkte, it's the continuation of the header
        if PUNKTE_RE.match(stripped):
            break
        # If we hit a structural keyword, stop
        if any(stripped.startswith(kw) for kw in [
            "Obligater Leistungsinhalt",
            "Fakultativer Leistungsinhalt",
            "Die Gebührenordnungsposition",
            "Abrechnungsbestimmung",
            "Anmerkung",
            "Berichtspflicht",
            "Aufwand in Min.",
        ]):
            break
        # If the line has Punkte at the end, take the text before it
        pm = PUNKTE_RE.search(stripped)
        if pm:
            pre = stripped[:pm.start()].strip()
            if pre:
                desc_parts.append(pre)
            break
        # If the line has a euro value, take the text before it
        em = EURO_RE.search(stripped)
        if em:
            pre = stripped[:em.start()].strip()
            if pre:
                desc_parts.append(pre)
            break
        # If it's an age tier, stop
        if AGE_TIER_RE.search(stripped):
            break
        # If it's a frequency term, stop
        if any(stripped.startswith(ft) for ft in FREQUENCY_TERMS):
            break
        # If the line starts with "- " it's a bullet, stop
        if stripped.startswith("- "):
            break
        # Otherwise it's description continuation
        if stripped:
            desc_parts.append(stripped)
        else:
            break  # empty line means end of description

    desc = " ".join(desc_parts)
    # Clean up extra whitespace
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc


def parse_age_tiers(body: str) -> list[dict] | None:
    """Extract age-tiered pricing from body text."""
    tiers = []
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = AGE_TIER_RE.search(line)
        if m:
            age_range = m.group(0)
            # Clean up the age_range: remove partial "Lebensjahr" artifacts
            age_range = re.sub(r"Lebensjahr(?:es)?$", "Lebensjahr", age_range)
            # Euro might be on this line or the next
            euro = parse_euro(line)
            punkte = parse_punkte(line)
            # Check next line for Punkte if not found
            if punkte is None and i + 1 < len(lines):
                punkte = parse_punkte(lines[i + 1].strip())
                if punkte is not None:
                    # Also check this next line for euro if we didn't get it
                    if euro is None:
                        euro = parse_euro(lines[i + 1].strip())
                    i += 1
            # Also check for euro on the same line after the age text
            if euro is None:
                euro = parse_euro(line)

            tiers.append({
                "age_range": age_range.strip(),
                "euro": euro,
                "punkte": punkte,
            })
        i += 1

    return tiers if tiers else None


def parse_leistungsinhalt(body: str, keyword: str) -> list[str]:
    """Extract bullet points from Obligater/Fakultativer Leistungsinhalt sections."""
    items = []
    # Find the section
    idx = body.find(keyword)
    if idx < 0:
        return items

    # Get text after the keyword
    after = body[idx + len(keyword):]
    lines = after.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Stop at the next section
        if any(stripped.startswith(kw) for kw in [
            "Obligater Leistungsinhalt",
            "Fakultativer Leistungsinhalt",
            "Die Gebührenordnungsposition",
            "Abrechnungsbestimmung",
            "Anmerkung",
            "Berichtspflicht",
            "Aufwand in Min.",
        ]):
            if stripped.startswith(keyword):
                continue  # skip self
            break
        # Also stop at frequency terms that signal end of content section
        if any(stripped.startswith(ft) for ft in FREQUENCY_TERMS):
            break
        # Also stop at age tier lines
        if AGE_TIER_RE.search(stripped):
            break
        # Also stop at euro/punkte lines that aren't part of bullets
        if re.match(r"^\d{1,3}(?:\.\d{3})*,\d{2}\s*€$", stripped) or re.match(r"^\d+\s+Punkte$", stripped):
            break
        # Collect bullet points
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif stripped.startswith("–"):
            items.append(stripped[1:].strip())
        elif items and not stripped.startswith(("Die ", "Im ", "Bei ", "Für ", "Der ", "Das ")):
            # Continuation of previous bullet
            items[-1] += " " + stripped
    return items


def expand_code_range(start: str, end: str) -> list[str]:
    """Expand a code range like '01410 bis 01413' into individual codes."""
    try:
        s = int(start)
        e = int(end)
        if e < s or e - s > 50:  # sanity check
            return [start, end]
        return [f"{c:05d}" for c in range(s, e + 1)]
    except ValueError:
        return [start, end]


def parse_exclusions(body: str) -> list[str]:
    """Extract exclusion codes from 'ist nicht neben' patterns."""
    exclusions: set[str] = set()

    # Normalize whitespace so line-broken text matches regex
    normalized_body = re.sub(r"\s+", " ", body)

    for m in EXCLUSION_RE.finditer(normalized_body):
        fragment = m.group(1)
        # Expand ranges
        for rm in CODE_RANGE_RE.finditer(fragment):
            exclusions.update(expand_code_range(rm.group(1), rm.group(2)))
        # Individual codes (not part of ranges)
        range_spans = set()
        for rm in CODE_RANGE_RE.finditer(fragment):
            range_spans.add((rm.start(), rm.end()))
        for cm in CODE_REF_RE.finditer(fragment):
            # Skip if this code is part of a range match
            in_range = False
            for rs, re_ in range_spans:
                if rs <= cm.start() < re_:
                    in_range = True
                    break
            if not in_range:
                exclusions.add(cm.group(0))

    return sorted(exclusions)


def parse_frequency(body: str) -> str | None:
    """Extract frequency/billing constraint."""
    # Normalize whitespace to handle line breaks
    normalized = re.sub(r"\s+", " ", body)
    for term in FREQUENCY_TERMS:
        if term in normalized:
            return term
    return None


def parse_zuschlag(first_line_rest: str, body: str) -> str | None:
    """Extract parent code if this is a Zuschlag (surcharge)."""
    combined = first_line_rest + "\n" + body
    normalized = re.sub(r"\s+", " ", combined)
    m = ZUSCHLAG_RE.search(normalized)
    if m:
        return m.group(1)
    return None


def parse_notes(body: str) -> list[str]:
    """Extract section-level exclusion notes (Abschnitte references)."""
    notes = []
    # Section-level exclusions
    for m in re.finditer(r"Gebührenordnungspositionen des Abschnitt(?:s|es)?\s+(\d+\.\d+)", body):
        notes.append(f"Abschnitt {m.group(1)}")
    return notes


def parse_code_block(block: dict) -> dict:
    """Parse a single code block into structured data."""
    code = block["code"]
    first_line = block["first_line_rest"]
    body = block["body"]
    page = block["page"]
    combined = first_line + "\n" + body

    # Description
    description = parse_description(first_line, body)

    # Euro / Punkte from the first line + first few lines of body
    header_zone = first_line + "\n" + "\n".join(body.split("\n")[:3])
    euro = parse_euro(header_zone)
    punkte = parse_punkte(header_zone)

    # Age tiers
    age_tiers = parse_age_tiers(body)

    # If we have age tiers but no top-level euro/punkte, that's expected
    # If we have euro/punkte AND age tiers, the top-level values are probably
    # from the first age tier — clear them and use tiers only
    if age_tiers and len(age_tiers) >= 2:
        # Multiple age tiers means this is age-tiered pricing
        # The top-level euro/punkte might be from the first tier
        euro = None
        punkte = None

    # Leistungsinhalt
    obligat = parse_leistungsinhalt(body, "Obligater Leistungsinhalt")
    fakultativ = parse_leistungsinhalt(body, "Fakultativer Leistungsinhalt")

    # Exclusions
    exclusions = parse_exclusions(body)

    # Frequency
    frequency = parse_frequency(combined)

    # Zuschlag
    zuschlag_to = parse_zuschlag(first_line, body)

    # Notes
    notes = parse_notes(body)

    # Chapter
    chapter = code[:2]

    return {
        "code": code,
        "description": description,
        "chapter": chapter,
        "euro": euro,
        "punkte": punkte,
        "age_tiers": age_tiers,
        "obligater_leistungsinhalt": obligat if obligat else None,
        "fakultativer_leistungsinhalt": fakultativ if fakultativ else None,
        "exclusions": exclusions if exclusions else None,
        "frequency": frequency,
        "zuschlag_to": zuschlag_to,
        "notes": notes if notes else None,
        "page": page,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_output(data: dict) -> list[str]:
    """Run automated validation checks. Returns list of issues."""
    issues: list[str] = []
    codes = data["codes"]
    chapters = data["chapters"]
    code_count = len(codes)

    # Code count sanity
    if code_count < 2000:
        issues.append(f"Low code count: {code_count} (expected 2000-5000)")
    elif code_count > 5000:
        issues.append(f"High code count: {code_count} (expected 2000-5000)")

    # Per-code checks
    for cid, entry in codes.items():
        # Chapter mapping
        ch = entry["chapter"]
        if ch not in chapters:
            issues.append(f"{cid}: chapter '{ch}' not in chapter map")

        # Euro/Punkte cross-check
        if entry["euro"] is not None and entry["punkte"] is not None:
            expected_euro = round(entry["punkte"] * ORIENTIERUNGSPUNKTWERT, 2)
            diff = abs(entry["euro"] - expected_euro)
            # Tolerance scales: small values 0.03€, large values proportional
            tolerance = max(0.03, expected_euro * 0.0001)
            if diff > tolerance:
                issues.append(
                    f"{cid}: euro {entry['euro']} vs punkte*OPW "
                    f"{expected_euro} (diff {diff:.2f})"
                )

        # Exclusion resolution
        if entry["exclusions"]:
            for exc in entry["exclusions"]:
                if exc not in codes:
                    # Not necessarily an error — could be appendix or regional code
                    pass  # soft check

    return issues


# ---------------------------------------------------------------------------
# Subset Generation
# ---------------------------------------------------------------------------


def generate_v2f_subset(data: dict) -> dict:
    """Generate a voice-to-fhir focused subset (~300-500 common codes)."""
    subset: dict[str, dict] = {}
    codes = data["codes"]

    for cid, entry in codes.items():
        ch = entry["chapter"]
        include = False

        # All chapter 01-02 codes (universal outpatient)
        if ch in ("01", "02"):
            include = True

        # All chapter 03 codes (hausarzt — primary V2F setting)
        if ch == "03":
            include = True

        # Versichertenpauschalen: codes ending in 000 (base consultation)
        if cid.endswith("000"):
            include = True

        # Grundpauschalen: codes ending in 210-212 (often age-stratified base codes)
        if cid[-3:] in ("210", "211", "212"):
            include = True

        # Zuschlag codes that reference included codes
        if entry.get("zuschlag_to") and entry["zuschlag_to"] in subset:
            include = True

        # Common diagnostic/therapeutic codes from key specialty chapters
        # Chapter 32: lab (common codes 32xxx)
        if ch == "32" and entry["euro"] is not None:
            include = True

        # Chapter 33: ultrasound
        if ch == "33":
            include = True

        # Chapter 34: radiology
        if ch == "34":
            include = True

        # Chapter 30: special care areas (common cross-specialty codes)
        if ch == "30":
            include = True

        if include:
            subset[cid] = entry

    return subset


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse EBM PDF into structured JSON")
    parser.add_argument("pdf_path", help="Path to the EBM PDF")
    parser.add_argument("-o", "--output", help="Output JSON path", default=None)
    parser.add_argument("--validate", action="store_true", help="Run validation checks")
    parser.add_argument(
        "--subset",
        choices=["voice-to-fhir"],
        help="Generate a subset for a specific consumer",
    )
    parser.add_argument("--start-page", type=int, default=18, help="First page to parse (default: 18)")
    parser.add_argument("--end-page", type=int, default=None, help="Last page to parse")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    # Default output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = pdf_path.parent / "ebm" / "ebm-2026q2.json"

    print(f"Extracting text from {pdf_path} (pages {args.start_page}-{args.end_page or 'end'})...")
    pages = extract_text_with_pages(str(pdf_path), args.start_page, args.end_page)
    print(f"  Extracted {len(pages)} pages with text")

    print("Splitting into code blocks...")
    blocks = split_into_code_blocks(pages)
    print(f"  Found {len(blocks)} code blocks")

    print("Parsing code blocks...")
    codes: dict[str, dict] = {}
    for block in blocks:
        parsed = parse_code_block(block)
        code_id = parsed["code"]
        if code_id in codes:
            # Keep the entry with more data (real definition > appendix stub)
            existing = codes[code_id]
            existing_richness = sum([
                existing["euro"] is not None,
                existing["punkte"] is not None,
                bool(existing.get("obligater_leistungsinhalt")),
                bool(existing.get("exclusions")),
                bool(existing.get("age_tiers")),
            ])
            new_richness = sum([
                parsed["euro"] is not None,
                parsed["punkte"] is not None,
                bool(parsed.get("obligater_leistungsinhalt")),
                bool(parsed.get("exclusions")),
                bool(parsed.get("age_tiers")),
            ])
            if new_richness > existing_richness:
                codes[code_id] = parsed
        else:
            codes[code_id] = parsed

    print(f"  Parsed {len(codes)} unique codes")

    # Discover chapters actually present
    found_chapters: dict[str, str] = {}
    for entry in codes.values():
        ch = entry["chapter"]
        if ch in CHAPTERS and ch not in found_chapters:
            found_chapters[ch] = CHAPTERS[ch]

    # Build output
    output = {
        "meta": {
            "source": "KBV",
            "title": "Einheitlicher Bewertungsmaßstab",
            "quarter": 2,
            "year": 2026,
            "created": "2026-03-31",
            "orientierungspunktwert": ORIENTIERUNGSPUNKTWERT,
            "code_count": len(codes),
            "parser_version": "1.0.0",
        },
        "chapters": dict(sorted(found_chapters.items())),
        "codes": dict(sorted(codes.items())),
    }

    # Validation
    if args.validate:
        print("Running validation...")
        issues = validate_output(output)
        if issues:
            print(f"  {len(issues)} issues found:")
            for issue in issues[:50]:
                print(f"    - {issue}")
            if len(issues) > 50:
                print(f"    ... and {len(issues) - 50} more")
        else:
            print("  All checks passed")

    # Subset
    if args.subset == "voice-to-fhir":
        subset = generate_v2f_subset(output)
        print(f"  V2F subset: {len(subset)} codes")
        output["v2f_subset_codes"] = sorted(subset.keys())

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
