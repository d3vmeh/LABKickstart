"""Generate and store student-facing setup guides for a kit, given a
teacher-uploaded lab-handout PDF. The LLM (gpt-4o-mini) produces a
structured materials list and numbered steps where every step has a
short "why" explaining the physics or measurement reason.

The route layer maps these exceptions onto HTTP status codes; see
`app.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from .kits import KitInfo

log = logging.getLogger(__name__)

DATA_DIR = Path("data/lab_guides")
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 12_000
LLM_MODEL = "gpt-4o-mini"


# ---------- Exceptions ----------

class LabGuideError(Exception):
    """Base for typed errors the route layer maps to HTTP codes."""


class PDFTooLargeError(LabGuideError): ...
class PDFInvalidError(LabGuideError): ...
class PDFEmptyTextError(LabGuideError): ...
class LLMConfigError(LabGuideError): ...
class LLMCallError(LabGuideError): ...


# ---------- JSON schema (constrains the LLM output) ----------

GUIDE_JSON_SCHEMA: dict[str, Any] = {
    "name": "lab_guide",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["materials", "steps"],
        "properties": {
            "materials": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["item", "quantity", "note"],
                    "properties": {
                        "item": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                        "note": {"type": "string"},
                    },
                },
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["n", "action", "reason"],
                    "properties": {
                        "n": {"type": "integer", "minimum": 1},
                        "action": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    },
    "strict": True,
}


SYSTEM_PROMPT = (
    "You are helping a high-school or introductory-college physics class "
    "set up a lab experiment safely and correctly. Given a teacher-supplied "
    "lab guide and the kit being used, produce a materials checklist and "
    "numbered setup steps. For every step include WHY it matters - the "
    "physics reason, the measurement quality reason, or the safety reason. "
    "Reasons should be short (1-3 sentences), specific, and assume an "
    "audience of students who are learning, not experts. Do not invent "
    "equipment that is not in the lab guide."
)


# ---------- Storage ----------

@dataclass
class LabGuideStore:
    data_dir: Path = DATA_DIR

    def _kit_dir(self, kit_id: str) -> Path:
        return self.data_dir / kit_id

    def get(self, kit_id: str) -> dict | None:
        p = self._kit_dir(kit_id) / "generated.json"
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def save(
        self,
        kit_id: str,
        generated: dict,
        *,
        pdf_bytes: bytes | None = None,
        text: str | None = None,
    ) -> None:
        d = self._kit_dir(kit_id)
        d.mkdir(parents=True, exist_ok=True)
        # Clean any prior source so we don't leave stale PDFs/txt behind.
        for stale in ("source.pdf", "source.txt"):
            (d / stale).unlink(missing_ok=True)
        if pdf_bytes is not None:
            (d / "source.pdf").write_bytes(pdf_bytes)
        if text is not None:
            (d / "source.txt").write_text(text)
        (d / "generated.json").write_text(json.dumps(generated, indent=2))

    def delete(self, kit_id: str) -> bool:
        import shutil
        d = self._kit_dir(kit_id)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True


# ---------- PDF extraction ----------

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Pull text out of a PDF. Raises PDFInvalidError or PDFEmptyTextError."""
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise PDFTooLargeError(
            f"PDF is {len(pdf_bytes) // 1024} KB; max is {MAX_PDF_BYTES // 1024} KB"
        )
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        if reader.is_encrypted:
            raise PDFInvalidError("PDF is encrypted")
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        text = "\n".join(chunks).strip()
    except PDFInvalidError:
        raise
    except Exception as e:
        raise PDFInvalidError(f"could not read PDF: {e}") from e
    if not text:
        raise PDFEmptyTextError(
            "no text in PDF (may be image-only; try a text PDF)"
        )
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


# ---------- LLM ----------

def _params_yaml(kit: KitInfo) -> str:
    if not kit.params:
        return "(none)"
    return "\n".join(
        f"  - {p.key}: {p.label} ({p.unit}){' [optional]' if not p.required else ''}"
        for p in kit.params
    )


def _build_user_prompt(kit: KitInfo, pdf_text: str) -> str:
    return (
        f"Kit: {kit.name}\n"
        f"Kit description: {kit.description}\n"
        f"Kit parameters the student will set:\n{_params_yaml(kit)}\n\n"
        "Lab guide text:\n"
        "---\n"
        f"{pdf_text}\n"
        "---"
    )


def _call_llm_json(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict,
    temperature: float = 0.3,
) -> dict:
    """One schema-constrained gpt-4o-mini call. Raises LLMCallError on
    any failure (transport, empty response, malformed JSON)."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMCallError("openai package not installed") from e

    client = OpenAI(api_key=api_key)
    try:
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=temperature,
        )
    except Exception as e:
        raise LLMCallError(f"OpenAI call failed: {e}") from e

    content = completion.choices[0].message.content
    if not content:
        raise LLMCallError("OpenAI returned empty content")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMCallError(f"OpenAI returned non-JSON: {e}") from e


def _validate(generated: dict) -> dict:
    """Lightweight server-side check (the LLM is already constrained by
    the schema, but trust-but-verify)."""
    if not isinstance(generated, dict):
        raise LLMCallError("guide is not an object")
    materials = generated.get("materials")
    steps = generated.get("steps")
    if not isinstance(materials, list) or not isinstance(steps, list):
        raise LLMCallError("guide missing materials/steps arrays")
    if not steps:
        raise LLMCallError("guide has no steps")
    for i, s in enumerate(steps, start=1):
        if not isinstance(s.get("action"), str) or not s["action"].strip():
            raise LLMCallError(f"step {i} has no action")
        if not isinstance(s.get("reason"), str) or not s["reason"].strip():
            raise LLMCallError(f"step {i} has no reason")
    return generated


# ---------- Top-level ----------

async def generate_and_save(
    kit_id: str,
    kit_info: KitInfo,
    api_key: str | None,
    store: LabGuideStore,
    *,
    pdf_bytes: bytes | None = None,
    text: str | None = None,
) -> dict:
    """Both PDF extraction (pypdf, CPU-bound) and the LLM call (sync OpenAI
    SDK) are dispatched via `asyncio.to_thread` so they don't block the
    event loop while the lab guide generates (~10 seconds typical).

    Generates a guide from either a PDF or pre-extracted text.

    Exactly one of `pdf_bytes` / `text` should be supplied. If a PDF is
    supplied it's also persisted as `source.pdf` for traceability; if text
    is supplied it's persisted as `source.txt`.
    """
    if not api_key:
        raise LLMConfigError("OPENAI_API_KEY is not configured on the server")
    if pdf_bytes is not None:
        body_text = await asyncio.to_thread(extract_pdf_text, pdf_bytes)
    elif text is not None:
        body_text = text.strip()
        if not body_text:
            raise PDFEmptyTextError("no text provided")
        if len(body_text) > MAX_TEXT_CHARS:
            body_text = body_text[:MAX_TEXT_CHARS]
    else:
        raise PDFInvalidError("provide either a PDF or text")
    prompt = _build_user_prompt(kit_info, body_text)
    last_error: Exception | None = None
    for attempt in (1, 2):                        # one retry
        try:
            generated = await asyncio.to_thread(
                _call_llm_json, api_key, SYSTEM_PROMPT, prompt, GUIDE_JSON_SCHEMA, 0.3,
            )
            generated = _validate(generated)
            break
        except LLMCallError as e:
            last_error = e
            log.warning("lab-guide LLM attempt %d failed: %s", attempt, e)
    else:
        # Both attempts failed; preserve the last exception's traceback.
        if last_error is not None:
            raise LLMCallError(str(last_error)) from last_error
        raise LLMCallError("LLM call failed")
    store.save(kit_id, generated, pdf_bytes=pdf_bytes, text=body_text if pdf_bytes is None else None)
    return generated


# ---------- Kit recommender ----------
# Given the lab handout text and the full kit registry, ask gpt-4o-mini
# which kit best matches the experiment described in the handout. Output
# is structurally constrained: the LLM picks kit_ids from a closed set,
# so it cannot hallucinate a kit that doesn't exist.

RECOMMENDER_SYSTEM_PROMPT = (
    "You are an expert at matching physics-lab procedures to the right "
    "data-acquisition equipment. Given a lab handout and a closed list of "
    "available kits (each tied to a specific BLE sensor module), pick up to "
    "three kits, ranked by how well they fit the experiment described. For "
    "each, give a one-sentence rationale grounded in what the handout asks "
    "students to measure. Do not recommend a kit not in the provided list."
)


def _recommender_schema(kit_ids: list[str]) -> dict:
    return {
        "name": "kit_recommendations",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["recommendations"],
            "properties": {
                "recommendations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kit_id", "rationale", "confidence"],
                        "properties": {
                            "kit_id": {"type": "string", "enum": kit_ids},
                            "rationale": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                        },
                    },
                },
            },
        },
        "strict": True,
    }


def _build_recommender_prompt(handout_text: str, kits: list[dict]) -> str:
    kit_lines = []
    for k in kits:
        mods = ", ".join(k.get("modules") or []) or "(any)"
        kit_lines.append(
            f"- id: {k['id']}\n"
            f"  name: {k['name']}\n"
            f"  description: {k['description']}\n"
            f"  required modules: {mods}"
        )
    return (
        "Available kits:\n"
        + "\n".join(kit_lines)
        + "\n\nLab handout text:\n---\n"
        + handout_text
        + "\n---\n\n"
        "Pick up to three kits ranked best-first. For each, explain in one "
        "sentence why it fits the experiment described."
    )


async def recommend_kits(
    *,
    kits: list[dict],
    api_key: str | None,
    pdf_bytes: bytes | None = None,
    text: str | None = None,
) -> list[dict]:
    """Return a ranked list of kit recommendations. Each item has
    `kit_id`, `rationale`, `confidence`, and (server-injected) `modules`
    derived from the kit registry so the UI can render hardware lists
    without trusting the LLM for that part."""
    if not api_key:
        raise LLMConfigError("OPENAI_API_KEY is not configured on the server")
    if not kits:
        raise LLMCallError("kit registry is empty")
    if pdf_bytes is not None:
        body_text = await asyncio.to_thread(extract_pdf_text, pdf_bytes)
    elif text is not None:
        body_text = text.strip()
        if not body_text:
            raise PDFEmptyTextError("no text provided")
        if len(body_text) > MAX_TEXT_CHARS:
            body_text = body_text[:MAX_TEXT_CHARS]
    else:
        raise PDFInvalidError("provide either a PDF or text")
    kit_ids = [k["id"] for k in kits]
    by_id = {k["id"]: k for k in kits}
    prompt = _build_recommender_prompt(body_text, kits)
    result = await asyncio.to_thread(
        _call_llm_json, api_key, RECOMMENDER_SYSTEM_PROMPT, prompt,
        _recommender_schema(kit_ids), 0.2,
    )
    recs = result.get("recommendations") or []
    if not recs:
        raise LLMCallError("recommender returned no recommendations")
    out: list[dict] = []
    for r in recs:
        kid = r.get("kit_id")
        if kid not in by_id:
            continue                                  # defensive: skip hallucinated ids
        out.append({
            "kit_id": kid,
            "name": by_id[kid]["name"],
            "rationale": r.get("rationale", ""),
            "confidence": r.get("confidence", "medium"),
            "modules": list(by_id[kid].get("modules") or []),
        })
    if not out:
        raise LLMCallError("no valid recommendations after filtering")
    return out
