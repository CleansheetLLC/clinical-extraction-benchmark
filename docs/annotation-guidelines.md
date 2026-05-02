# Annotation Guidelines

How to create verified FHIR R4 ground truth annotations for clinical transcripts.

## Principles

1. **Annotate what's stated, not what's implied.** If the transcript says "patient is on metformin," annotate a MedicationStatement. Don't infer diabetes unless it's explicitly stated.
2. **Use the most specific code available.** "Hypertension" → I10 (Essential hypertension), not R03.0 (Elevated blood-pressure reading).
3. **Two reviewers minimum.** Every annotation must be created by one person and verified by another.
4. **Valid FHIR or nothing.** Every annotation must be a valid FHIR R4 Bundle. Use `tools/validate.py` before submitting.

## Workflow

### Step 1: Read the transcript

Read the full transcript. Identify:
- Conditions / diagnoses (stated and historical)
- Medications (current and newly ordered)
- Allergies
- Vitals and lab results
- Orders (lab, imaging, procedure, referral)
- Family history
- Social history observations

### Step 2: Create the FHIR Bundle

Start from the template in `schemas/template-bundle.json`. For each identified entity:

1. Choose the correct FHIR resource type
2. Assign the appropriate code system and code
3. Fill required attributes (status, severity, dose, etc.)
4. Reference the common Patient and Encounter resources

### Step 3: Validate

```bash
python tools/validate.py annotations/en/soap-001.json
```

### Step 4: Create metadata

Create a metadata JSON file alongside the annotation (see `schemas/transcript-metadata.schema.json`):

```json
{
  "id": "en-soap-001",
  "language": "en",
  "workflow": "soap",
  "source": "original",
  "verified": true,
  "audio_file": "audio/en/soap-001.wav",
  "annotation_file": "annotations/en/soap-001.json",
  "specialty": ["internal-medicine"],
  "entity_counts": {
    "Condition": 3,
    "MedicationStatement": 2,
    "MedicationRequest": 1,
    "Observation": 4,
    "AllergyIntolerance": 1
  },
  "annotators": ["annotator-a", "reviewer-b"],
  "difficulty": "moderate",
  "notes": "Standard SOAP encounter with hypertension management"
}
```

### Step 5: Peer review

A second annotator reviews the FHIR Bundle against the transcript and either:
- Approves (sets `verified: true`)
- Returns with comments for revision

## Coding Conventions

### Conditions

| Field | Convention |
| ----- | ---------- |
| code.system | `http://hl7.org/fhir/sid/icd-10-cm` (US) or `http://fhir.de/CodeSystem/bfarm/icd-10-gm` (DE) |
| clinicalStatus | `active`, `resolved`, `inactive` |
| verificationStatus | `confirmed` (stated), `provisional` (suspected) |
| severity | Only if explicitly stated in transcript |

### Medications

| Field | Convention |
| ----- | ---------- |
| code.system | `http://www.nlm.nih.gov/research/umls/rxnorm` |
| status | `active` (current), `completed` (discontinued) |
| dosageInstruction | Only if dose/route/frequency stated |
| Use MedicationStatement for current meds, MedicationRequest for new orders |

### Observations (Vitals)

| Field | Convention |
| ----- | ---------- |
| code.system | `http://loinc.org` |
| valueQuantity | Numeric value + UCUM unit |
| component | Use for multi-part vitals (e.g., systolic/diastolic BP) |

### Allergies

| Field | Convention |
| ----- | ---------- |
| code.system | `http://www.nlm.nih.gov/research/umls/rxnorm` (drug) or SNOMED CT (substance) |
| reaction.severity | `mild`, `moderate`, `severe` — only if stated |
| type | `allergy` or `intolerance` based on transcript language |

## What NOT to Annotate

- **Implied conditions.** If the patient is on insulin but diabetes is never mentioned, do not add a Condition for diabetes.
- **Clinician reasoning.** "I think this might be..." is not a confirmed diagnosis unless the clinician states it as one.
- **Administrative data.** Appointment scheduling, insurance information, etc. are out of scope.
- **Normal findings.** "Lungs clear" is not an Observation unless it's clinically relevant in context (e.g., ruling out pneumonia in an ED visit).

## File Naming

```
{lang}-{workflow}-{sequence}.{ext}

Examples:
  en-soap-001.txt          (transcript)
  en-soap-001.json         (FHIR annotation)
  en-soap-001.meta.json    (metadata)
  en-soap-001.wav          (audio, if available)
```

## Quality Checklist

Before submitting an annotation:

- [ ] Bundle passes `tools/validate.py`
- [ ] Every Condition has a valid ICD-10 code
- [ ] Every Medication has a valid RxNorm code
- [ ] Every Observation has a valid LOINC code
- [ ] Entity counts in metadata match actual bundle contents
- [ ] No entities annotated that aren't explicitly stated in transcript
- [ ] Second reviewer has verified
