"""Generate and store student-facing setup guides for a kit, given a
teacher-uploaded lab-handout PDF. The LLM (gpt-4o-mini) produces a
structured materials list and numbered steps where every step has a
short "why" explaining the physics or measurement reason.

The route layer maps these exceptions onto HTTP status codes; see
`app.py`.
"""
from __future__ import annotations

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
        d = self._kit_dir(kit_id)
        if not d.exists():
            return False
        for child in d.iterdir():
            child.unlink()
        d.rmdir()
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


def _call_openai(api_key: str, user_prompt: str) -> dict:
    """One call to gpt-4o-mini. Raises LLMCallError on any failure."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMCallError("openai package not installed") from e

    client = OpenAI(api_key=api_key)
    try:
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": GUIDE_JSON_SCHEMA,
            },
            temperature=0.3,
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
    """Generate a guide from either a PDF or pre-extracted text.

    Exactly one of `pdf_bytes` / `text` should be supplied. If a PDF is
    supplied it's also persisted as `source.pdf` for traceability; if text
    is supplied it's persisted as `source.txt`.
    """
    if not api_key:
        raise LLMConfigError("OPENAI_API_KEY is not configured on the server")
    if pdf_bytes is not None:
        body_text = extract_pdf_text(pdf_bytes)   # raises PDF*Error
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
            generated = _call_openai(api_key, prompt)
            generated = _validate(generated)
            break
        except LLMCallError as e:
            last_error = e
            log.warning("lab-guide LLM attempt %d failed: %s", attempt, e)
    else:
        raise LLMCallError(str(last_error) if last_error else "LLM call failed")
    store.save(kit_id, generated, pdf_bytes=pdf_bytes, text=body_text if pdf_bytes is None else None)
    return generated
