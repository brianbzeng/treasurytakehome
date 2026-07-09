"""Replaceable multimodal extraction providers."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from treasury_app.models import (
    ExtractedField,
    LabelExtraction,
    WarningObservation,
)


class ProviderError(RuntimeError):
    """Safe, user-facing provider failure."""


class ExtractionProvider(Protocol):
    name: str

    def extract(self, images: list["ImageInput"]) -> LabelExtraction:
        """Extract structured observations from label images."""


@dataclass(frozen=True)
class ImageInput:
    content: bytes
    mime_type: str
    filename: str


SYSTEM_PROMPT = """
You extract evidence from United States alcohol beverage label artwork.
Return JSON only. Transcribe what is visibly present; never infer a missing
value and never copy an expected application value because none is provided.

Use exactly this object shape:
{
  "brand_name": {"value": string|null, "evidence": string|null, "confidence": 0..1},
  "class_type": {"value": string|null, "evidence": string|null, "confidence": 0..1},
  "alcohol_content": {"value": string|null, "evidence": string|null, "confidence": 0..1},
  "net_contents": {"value": string|null, "evidence": string|null, "confidence": 0..1},
  "producer_name_address": {"value": string|null, "evidence": string|null, "confidence": 0..1},
  "country_of_origin": {"value": string|null, "evidence": string|null, "confidence": 0..1},
  "government_warning": {
    "verbatim_text": string|null,
    "heading_text": string|null,
    "heading_bold": boolean|null,
    "legible": boolean|null,
    "evidence": string|null,
    "confidence": 0..1
  },
  "raw_text": string|null,
  "notes": [string]
}

For government_warning.verbatim_text, preserve capitalization, punctuation,
wording, and order exactly as visible. Use null and low confidence when text or
formatting cannot be determined. Do not provide a compliance verdict.
""".strip()


class MiMoProvider:
    name = "Xiaomi MiMo"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        if not api_key:
            raise ProviderError(
                "MiMo is not configured. Add MIMO_API_KEY to the service "
                "environment or enable mock mode for local development."
            )
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=1,
        )

    def extract(self, images: list[ImageInput]) -> LabelExtraction:
        content: list[dict] = []
        for image in images:
            encoded = base64.b64encode(image.content).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.mime_type};base64,{encoded}"
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    "Extract all requested fields from these views of one "
                    "product label. Return one combined JSON object."
                ),
            }
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=1800,
            )
            message = response.choices[0].message.content
            if not message:
                raise ProviderError("The image service returned an empty response.")
            payload = json.loads(message)
            return LabelExtraction.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, IndexError) as exc:
            raise ProviderError(
                "The image service returned an invalid result. Please retry."
            ) from exc
        except APITimeoutError as exc:
            raise ProviderError(
                "The image review timed out. Please retry with a smaller image."
            ) from exc
        except APIConnectionError as exc:
            raise ProviderError(
                "The image service could not be reached. Please retry shortly."
            ) from exc
        except APIStatusError as exc:
            if exc.status_code == 429:
                message = "The image service is busy. Please retry shortly."
            else:
                message = "The image service could not process this label."
            raise ProviderError(message) from exc


class MockProvider:
    name = "Mock provider"

    def extract(self, images: list[ImageInput]) -> LabelExtraction:
        return LabelExtraction(
            brand_name=ExtractedField(
                value="OLD TOM DISTILLERY",
                evidence="OLD TOM DISTILLERY",
                confidence=0.99,
            ),
            class_type=ExtractedField(
                value="Kentucky Straight Bourbon Whiskey",
                evidence="Kentucky Straight Bourbon Whiskey",
                confidence=0.98,
            ),
            alcohol_content=ExtractedField(
                value="45% Alc./Vol. (90 Proof)",
                evidence="45% Alc./Vol. (90 Proof)",
                confidence=0.99,
            ),
            net_contents=ExtractedField(
                value="750 mL", evidence="750 mL", confidence=0.99
            ),
            producer_name_address=ExtractedField(
                value="Old Tom Distillery, Louisville KY",
                evidence="Old Tom Distillery, Louisville KY",
                confidence=0.96,
            ),
            government_warning=WarningObservation(
                verbatim_text=(
                    "GOVERNMENT WARNING: (1) According to the Surgeon General, "
                    "women should not drink alcoholic beverages during pregnancy "
                    "because of the risk of birth defects. (2) Consumption of "
                    "alcoholic beverages impairs your ability to drive a car or "
                    "operate machinery, and may cause health problems."
                ),
                heading_text="GOVERNMENT WARNING:",
                heading_bold=True,
                legible=True,
                evidence="GOVERNMENT WARNING: (1) According to...",
                confidence=0.98,
            ),
            raw_text="Mock development extraction",
            notes=["Mock mode is active; no image analysis was performed."],
        )
