# Lab Guide LLM Generation — Design

## Goal

Let a physics teacher upload a lab-guide PDF for a kit. The server extracts
the text, sends it to gpt-4o-mini, and stores a structured setup walkthrough
(materials list + numbered steps with paired rationale). Students who select
that kit see the generated guide in the dashboard.

## Decisions

| Question                           | Choice                                              |
|------------------------------------|-----------------------------------------------------|
| Audience for LLM output            | Students (teacher reviews implicitly by re-uploading) |
| Input format                       | PDF upload only                                     |
| Attachment to data model           | One active guide per kit                            |
| Output structure                   | Structured JSON: materials + steps with `action` + `reason` |
| LLM model                          | `gpt-4o-mini`                                       |
| Cache policy                       | Generate once at upload; cached on disk; re-upload to refresh |
| Auth                               | None in v0 — anyone with URL can upload             |

## Architecture

New module `src/labkickstart/lab_guides.py` owns:

1. PDF text extraction (`pypdf`).
2. LLM call (`openai>=1.0`, `gpt-4o-mini`, `response_format=json_schema`).
3. Validation against the agreed JSON schema.
4. Disk persistence under `data/lab_guides/<kit_id>/`.

The module is independent of routing, kits, and runs. It exposes:

```python
class LabGuideStore:
    def get(kit_id: str) -> dict | None
    def delete(kit_id: str) -> bool

async def generate_and_save(
    kit_id: str,
    pdf_bytes: bytes,
    kit_info: KitInfo,
    api_key: str,
) -> dict
```

`generate_and_save` does extract → LLM → validate → write, and returns the
JSON. It raises typed exceptions the route layer maps to HTTP codes.

## Storage layout

```
data/lab_guides/<kit_id>/
  source.pdf       the file the teacher uploaded
  generated.json   the structured guide
```

The `kit_id` matches `KitInfo.id` (e.g. `photogate`). One guide per kit.
`data/lab_guides/` is added to `.gitignore` (treated like `data/runs/`).

## API endpoints

```
POST   /api/kits/{kit_id}/lab_guide      multipart: file=<pdf>
                                          overwrites any existing guide for the kit
       200  {materials, steps}            generated and cached
       400  invalid PDF or empty extracted text or unknown kit_id
       413  PDF > 5 MB
       502  LLM call failed after one retry
       503  OPENAI_API_KEY not set on the server

GET    /api/kits/{kit_id}/lab_guide
       200  {materials, steps}            cached guide
       404  no guide uploaded yet

DELETE /api/kits/{kit_id}/lab_guide
       204  removed
```

The kit-list endpoint (`GET /api/kits`) is unchanged. The UI fetches lab
guides separately so the kit registry stays purely about hardware/derivation.

## JSON schema for the generated guide

```json
{
  "materials": [
    {"item": "Track (>=1.5 m)", "quantity": 1, "note": "Level the surface."}
  ],
  "steps": [
    {"n": 1,
     "action": "Place gate A 20 cm from the launch point.",
     "reason": "Far enough that the cart has cleared the launch impulse but not so far that..."}
  ]
}
```

- `materials[].item` and `steps[].action` are required, non-empty strings.
- `materials[].quantity` is a positive integer. `note` is optional.
- `steps[].n` is sequential starting at 1. `reason` is required (the whole
  point of this feature).

The OpenAI call uses `response_format` with this schema so the model is
constrained to produce conforming JSON. Server-side, we still validate
before saving — if the model returns non-conforming JSON we retry once,
then return 502.

## LLM prompt

System prompt (constant):

```
You are helping a high-school or introductory-college physics class set up a
lab experiment safely and correctly. Given a teacher-supplied lab guide and
the kit being used, produce a materials checklist and numbered setup steps.
For every step include WHY it matters - the physics reason, the measurement
quality reason, or the safety reason. Reasons should be short (1-3
sentences), specific, and assume an audience of students who are learning,
not experts. Do not invent equipment that is not in the lab guide.
```

User prompt (templated):

```
Kit: {kit_name}
Kit description: {kit_description}
Kit parameters the student will set:
{params_yaml}

Lab guide text:
---
{extracted_text}
---
```

PDF text is truncated to ~12 000 characters before being sent (well under
gpt-4o-mini's context but large enough for any reasonable lab handout).

## UI

In the Kit section, **right below the existing diagrams dropdown** and
above the parameter inputs:

- New `<details>` element titled **"Lab guide"**, open by default once a
  guide exists.
- Empty state: `[Choose PDF]` file input + `[Upload]` button + a small
  reminder line ("Generates with gpt-4o-mini, takes ~10 s").
- Generating state: button disabled, spinner, text "Generating with
  gpt-4o-mini…".
- Loaded state:
    - Two-column-ish layout: **Materials** list, then **Steps** stacked
      below.
    - Each step renders as a card with `n. action` visible and a
      collapsible `<details>` containing the reason. Same dropdown
      affordance as the existing experiment-setup diagram.
    - Subtle "Replace" text link at the bottom that re-opens the file
      picker.
- Error state: red banner under the upload row with the server's `detail`
  message.

The UI calls:

- `GET /api/kits/{kit_id}/lab_guide` on kit selection (alongside the
  existing kit info fetch). 404 → empty state.
- `POST` on upload, then re-renders.
- `DELETE` only on explicit "remove guide" — for v0 we don't expose this in
  the UI; "Replace" just re-uploads.

## Error handling

| Cause                         | Server response | UI behavior                                  |
|-------------------------------|-----------------|----------------------------------------------|
| PDF > 5 MB                    | 413             | Banner: "PDF too large (max 5 MB)"           |
| Encrypted / unreadable PDF    | 400             | Banner: "Could not read PDF; try a text PDF" |
| Empty text after extraction   | 400             | Banner: "No text in PDF (image-only?)"       |
| `OPENAI_API_KEY` missing      | 503             | Banner: "Server is not configured for LLM"   |
| OpenAI network/HTTP error     | 502 (after 1 retry) | Banner: "LLM call failed - try again"     |
| OpenAI returned non-JSON      | 502 (after 1 retry) | Same                                      |
| Unknown kit_id                | 400             | Banner with the detail                       |

## Dependencies added

In `requirements.txt`:

- `openai>=1.0`
- `pypdf>=4.0`
- `python-multipart>=0.0.7`  (FastAPI multipart upload)
- `python-dotenv>=1.0`        (reads `.env` at server startup)

A `.env.example` is committed showing `OPENAI_API_KEY=`. The actual `.env`
is gitignored (already covered by the broad `.env` ignore we'll add).
`labkickstart.app` calls `load_dotenv()` once at module import.

## YAGNI

Out of scope for v0:

- Versioning / history of guides.
- Multiple guides per kit.
- Editing the generated JSON in the UI.
- Auth / teacher-only gating.
- Streaming the LLM response token-by-token.
- Re-using the source PDF for anything other than confirming what was uploaded.
