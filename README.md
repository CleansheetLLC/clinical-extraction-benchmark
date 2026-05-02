# Clinical Extraction Benchmark

An open benchmark for evaluating clinical NLP pipelines that extract structured FHIR R4 resources from clinical text and speech. Covers the full chain: **audio → transcript → structured FHIR data**.

## What This Is

Existing medical speech datasets (MultiMed, n2c2, United-MedSyn) provide audio and transcripts, but none provide verified FHIR R4 extraction ground truth. Existing clinical NER datasets annotate entities but don't produce valid FHIR resources.

This benchmark fills the gap: **human-verified expected FHIR R4 Bundles for clinical transcripts**, enabling reproducible evaluation of any extraction pipeline against a common standard.

## Repository Structure

```
clinical-extraction-benchmark/
├── transcripts/               Verified clinical text (input to extraction)
│   ├── en/                   English
│   ├── de/                   German
│   └── fr/                   French
├── annotations/               Expected FHIR R4 Bundles (ground truth output)
│   ├── en/
│   ├── de/
│   └── fr/
├── audio/                     Audio files (where available)
│   ├── en/
│   ├── de/
│   └── fr/
├── schemas/                   JSON schemas for validation
├── tools/                     Scoring and evaluation scripts
└── docs/                      Methodology, annotation guidelines, data sources
```

## Data Layers

### Layer 1: Transcripts

Clinical text from multiple sources:

| Source | Languages | Type | License | Status |
| ------ | --------- | ---- | ------- | ------ |
| Original (this repo) | EN, DE | Scripted synthetic clinical scenarios | CC BY-SA 4.0 | In progress |
| [MultiMed](https://github.com/leduckhai/MultiMed) | EN, DE, FR, VI, ZH | Real clinical audio + transcripts | Research license | Reference (not redistributed) |
| [n2c2](https://n2c2.dbmi.hms.harvard.edu/data-sets) | EN | Deidentified clinical notes | DUA required | Reference (not redistributed) |

Transcripts from external datasets are **referenced, not redistributed**. Follow the links above to obtain them under their respective licenses. This repo provides the FHIR extraction annotations that layer on top.

### Layer 2: FHIR R4 Annotations (Novel Contribution)

Each transcript has a corresponding verified FHIR R4 Bundle in `annotations/`. The bundle contains the expected extraction output:

- **Condition** (ICD-10-CM / SNOMED-CT)
- **MedicationRequest** / **MedicationStatement** (RxNorm)
- **Observation** (LOINC) -- vitals, lab results
- **AllergyIntolerance** (RxNorm / SNOMED-CT)
- **Procedure** (CPT / SNOMED-CT)
- **ServiceRequest** (lab orders, imaging, referrals)
- **FamilyMemberHistory**

### Layer 3: Audio (Where Available)

Original scripted scenarios include recorded audio. External dataset audio is referenced, not redistributed.

## Annotation Format

Each annotation is a valid FHIR R4 Bundle (JSON) that could be submitted to a FHIR server. This means:

- Valid resource types with required fields
- Coded values use standard terminologies (ICD-10-CM, RxNorm, LOINC, SNOMED-CT)
- Resources reference a common Patient and Encounter
- Bundle type is `collection` (not `transaction`, since this is ground truth, not a submission)

See `schemas/` for JSON Schema validation and `docs/annotation-guidelines.md` for the annotation methodology.

## Evaluation

### Scoring

The `tools/` directory contains scripts for comparing pipeline output against ground truth:

```bash
# Compare a single extraction against ground truth
python tools/score.py --predicted output.json --expected annotations/en/soap-001.json

# Batch score across a dataset
python tools/batch_score.py --predicted-dir results/ --expected-dir annotations/en/
```

### Metrics

| Metric | What It Measures |
| ------ | ---------------- |
| **Entity F1** | Per-resource-type precision/recall/F1 (did the pipeline find the right conditions, meds, etc.?) |
| **Code accuracy** | Of correctly identified entities, did the pipeline assign the right ICD-10/RxNorm/LOINC code? |
| **Attribute completeness** | Of correctly identified entities, were attributes (dose, severity, status) extracted? |
| **Bundle validity** | Is the output a valid FHIR R4 Bundle? |

## Scenario Coverage

Transcripts are organized by clinical workflow:

| Workflow | Tag | Description |
| -------- | --- | ----------- |
| General | `general` | Unstructured clinical encounter |
| SOAP | `soap` | Subjective/Objective/Assessment/Plan format |
| H&P | `hp` | History and Physical |
| Emergency | `emergency` | ED encounter, high acuity |
| SAMPLER+S | `samplers` | Pre-hospital / emergency (includes German Schmerz variant) |
| Intake | `intake` | New patient intake |
| Follow-up | `followup` | Return visit |
| Discharge | `discharge` | Discharge summary |
| Specialty | `cardiology`, `neurology`, etc. | Specialty-specific encounters |

## Contributing

Contributions welcome. See `docs/contributing.md` for guidelines.

### Ways to contribute

1. **Record audio**: Scripted clinical scenarios in any language (see `docs/recording-guidelines.md`)
2. **Annotate transcripts**: Add verified FHIR R4 Bundles for existing transcripts
3. **Add languages**: Extend coverage beyond EN/DE/FR
4. **Improve tooling**: Scoring scripts, validation, visualization

### Quality requirements

- All transcripts must be **synthetic** (scripted scenarios, never real patient data)
- All FHIR annotations must be **independently verified** by a second reviewer
- All coded values must be **valid** in their respective terminology (ICD-10-CM, RxNorm, LOINC)
- Audio must be **clearly recorded** with metadata (language, accent, noise level, equipment)

## License

- **Original content** (transcripts, annotations, audio, tools): [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- **External datasets**: Referenced only, subject to their own licenses

## Citation

If you use this benchmark in research, please cite:

```
@misc{clinical-extraction-benchmark,
  title={Clinical Extraction Benchmark: FHIR R4 Ground Truth for Clinical NLP Evaluation},
  author={Cleansheet LLC},
  year={2026},
  url={https://github.com/cleansheet-llc/clinical-extraction-benchmark}
}
```
