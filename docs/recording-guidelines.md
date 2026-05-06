# Recording Guidelines

Technical specifications for contributing audio recordings of scripted clinical scenarios.

## Requirements

### Content

- **Synthetic only.** All scenarios must be scripted with fictional patients. Never record real encounters.
- **Clinically realistic.** Scripts should reflect actual clinical workflow patterns (SOAP, SBAR, SAMPLER+S, etc.).
- **Complete encounters.** Include the full workflow from chief complaint through plan, not just fragments.

### Audio Quality

| Parameter | Requirement | Notes |
| --------- | ----------- | ----- |
| Format | WAV (preferred), FLAC, or MP3 | WAV for archival quality; MP3 acceptable for contributed recordings |
| Sample rate | 16 kHz minimum | 44.1 kHz preferred |
| Bit depth | 16-bit minimum | |
| Channels | Mono | Stereo acceptable if single speaker |
| Duration | 1-10 minutes per recording | Typical clinical encounter length |
| File size | Git LFS handles large files | Keep under 50 MB per file |

### Recording Environment

| Condition | Target | Notes |
| --------- | ------ | ----- |
| Background noise | Minimal | Quiet room preferred; hospital ambient noise acceptable if realistic |
| Microphone | Consistent distance | Headset, lapel, or desk mic; avoid built-in laptop mic |
| Speaker | Natural pace | Clinical speaking rate, not dictation speed |

### Metadata

Every recording must have a corresponding metadata file. Include:

- Language and accent/dialect (e.g., "en-US", "de-DE", "en-IN")
- Recording equipment (microphone model, recording software)
- Noise conditions (quiet room, simulated hospital ambient, etc.)
- Speaker role (clinician monologue, clinician-patient dialogue, multi-provider)
- Number of speakers

## Scenario Scripts

### Writing a script

Good benchmark scenarios:

1. **Cover common entity types.** Include at least: 2-3 conditions, 2-3 medications, 1 allergy, 3-4 vitals.
2. **Include edge cases.** Negated findings ("denies chest pain"), historical conditions ("history of MI in 2019"), family history.
3. **Match a workflow.** Use a real clinical documentation framework (SOAP, SBAR, H&P, etc.).
4. **Vary difficulty.** Simple (clear, structured) through complex (multiple problems, medication changes, ambiguous phrasing).

### Script template

```
[SCENARIO METADATA]
ID: {lang}-{workflow}-{sequence}
Workflow: SOAP
Specialty: Internal Medicine
Difficulty: Moderate
Speakers: 1 (clinician monologue)
Expected entities: 3 conditions, 4 medications, 1 allergy, 5 vitals

[SCRIPT]
(Begin transcript)
...
(End transcript)

[EXPECTED ENTITIES]
Conditions: Essential hypertension (I10), Type 2 diabetes (E11.9), Hyperlipidemia (E78.5)
Medications: Metformin 1000mg BID (RxNorm 861004), Lisinopril 20mg daily (RxNorm 314076), ...
Allergies: Penicillin - rash (RxNorm 7980)
Vitals: BP 138/82, HR 76, Temp 98.6F, SpO2 98%, Weight 92kg
```

## Multi-Speaker Recordings

Dialogue transcripts (`workflow: dialogue`) feature explicit provider-patient conversations with speaker labels. These require a different recording approach than single-speaker monologues.

### Setup

| Parameter | Requirement | Notes |
| --------- | ----------- | ----- |
| Speakers | 2 (one provider, one patient) | Each person reads their labeled lines |
| Microphone | Single shared mic | Place between both speakers at equal distance |
| Pacing | Natural conversational | Pause briefly between turns; don't rush or overlap |
| Channels | Mono | Do not use separate channels per speaker |

### Recording process

1. **Assign roles.** One person reads all `Provider:` / `Médica:` lines, the other reads all `Patient:` / `Paciente:` lines.
2. **Single microphone.** Place a desk or table mic between both speakers. This simulates a real exam-room capture.
3. **Natural pacing.** Leave a brief pause (~1 second) between speaker turns. Do not read speaker labels aloud — only the dialogue text.
4. **Complete the encounter.** Record the full transcript in one take when possible. If you need to restart, re-record the entire encounter.

### Dialogue script template

```
[SCENARIO METADATA]
ID: {lang}-dialogue-{sequence}
Workflow: dialogue
Specialty: Internal Medicine, Social Work
Difficulty: Complex
Speakers: 2 (provider, patient)
Expected entities: 2 conditions, 1 medication, 5 observations, 3 service requests

[SCRIPT]
Provider: [opening question]
Patient: [response with clinical/social details]
Provider: [follow-up question]
Patient: [response]
...
Provider: [assessment and plan]

[EXPECTED ENTITIES]
Conditions: ...
Observations: ...
ServiceRequests: ...
```

## Multi-Language Considerations

| Language | Code system | Notes |
| -------- | ----------- | ----- |
| English (US) | ICD-10-CM, RxNorm, LOINC | Default |
| English (other) | ICD-10-CM or ICD-10 (WHO) | Specify in metadata |
| German | ICD-10-GM, PZN or ATC for medications | OPS for procedures |
| French | ICD-10 (WHO), CIS/CIP for medications | |

## File Naming

```
audio/{lang}/{lang}-{workflow}-{sequence}.wav
transcripts/{lang}/{lang}-{workflow}-{sequence}.txt
annotations/{lang}/{lang}-{workflow}-{sequence}.json
```

## Consent

By contributing a recording, you confirm:
- The content is entirely fictional (no real patient data)
- You have the right to contribute the recording
- You agree to the CC BY-SA 4.0 license
