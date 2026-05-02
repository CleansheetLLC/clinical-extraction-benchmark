# Contributing

Thank you for contributing to the Clinical Extraction Benchmark. This guide covers what we need and how to submit.

## What We Need

### Priority: FHIR Annotations

The most valuable contribution is verified FHIR R4 annotations for existing transcripts. If you have clinical domain expertise and can annotate transcripts with correct ICD-10, RxNorm, LOINC, and SNOMED-CT codes, this is where you'll have the most impact.

### Audio Recordings

Scripted clinical scenario recordings in any language. Requirements:

- **Synthetic only.** Scripted scenarios with fictional patients. Never record real clinical encounters.
- **Clear audio.** Quiet environment, consistent microphone distance.
- **Metadata.** Language, accent/dialect, recording equipment, noise conditions.
- **Matching transcript.** Verbatim transcript of the recording.

See `docs/recording-guidelines.md` for technical specifications.

### New Languages

Extending coverage beyond EN/DE/FR. Each language needs:
- At least 5 transcripts across different workflows
- Verified FHIR annotations using locale-appropriate code systems
- A native speaker as annotator or reviewer

### Tooling

Scoring scripts, validation improvements, visualization tools. See `tools/` for what exists.

## How to Submit

### For annotations and transcripts

1. Fork the repository
2. Create your files following the naming convention in `docs/annotation-guidelines.md`
3. Run `python tools/validate.py` on all new annotations
4. Submit a pull request with:
   - The transcript file(s)
   - The FHIR annotation file(s)
   - The metadata file(s)
   - A note about your clinical domain background (for reviewer assignment)

### For audio

Audio files are stored via Git LFS. Before contributing audio:

1. Install Git LFS: `git lfs install`
2. Audio files in `audio/` are tracked automatically (see `.gitattributes`)
3. Accepted formats: WAV (preferred), FLAC, MP3
4. Maximum 10 minutes per recording

### For tooling

Standard pull request workflow. Include tests for new scoring logic.

## Review Process

1. All annotations require review by at least one person with clinical domain knowledge
2. Code validity is checked automatically (ICD-10, RxNorm, LOINC lookups)
3. Reviewers check for annotation completeness (no missed entities) and accuracy (correct codes)
4. Expect 1-2 weeks for review turnaround

## Code of Conduct

- All contributed content must be synthetic (fictional patients, scripted scenarios)
- Never contribute real patient data, even if deidentified
- Respect external dataset licenses (MultiMed, n2c2, etc.)
- Credit co-annotators in metadata

## Questions

Open an issue for questions about annotation guidelines, tooling, or contribution process.
