"""Replaceable multimodal extraction providers."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from treasury_app.models import (
    ApplicationData,
    ExtractedField,
    LabelExtraction,
    WarningObservation,
)


class ProviderError(RuntimeError):
    """Safe, user-facing provider failure."""


class ExtractionProvider(Protocol):
    name: str

    def extract(
        self,
        images: list["ImageInput"],
        application: ApplicationData,
    ) -> LabelExtraction:
        """Extract structured observations from label images."""


@dataclass(frozen=True)
class ImageInput:
    content: bytes
    mime_type: str
    filename: str


SYSTEM_PROMPT = """
You extract evidence from United States alcohol beverage label artwork.
Return JSON only.

The application identifies the beverage type as distilled spirits, wine, or
malt beverage. Use that profile only to interpret the requested evidence:
proof applies only to distilled spirits, so return null for proof on wine and
malt beverage labels. Do not infer a commodity-specific compliance decision.

You will receive expected text candidates from an application for the brand,
class/type, producer/address, and possibly country of origin. Your role for
those fields is to locate the expected candidate in the artwork, not to decide
which other large or prominent wording is the legal brand or class/type.

For each expected text candidate:
- Set expected_value_found to true only when the candidate, or a harmless
  case/punctuation/spacing variation of it, is visibly supported by the label.
- Cite the exact visible phrase or surrounding line in evidence.
- If the candidate is not confidently visible, set expected_value_found to
  false and value to null. Do not substitute a marketing term, fanciful name,
  slogan, or another candidate as a competing field value.
- Do not copy a candidate into value or evidence unless it is actually visible
  in the artwork.

For brand_name, this is an evidence-location check, not a judgment about which
text is visually most prominent. Search the entire label, including a
“Bottled by,” “Produced by,” or logo statement. Treat common legal-name suffix
variants as the same name when every other word matches: COMPANY/CO.,
INCORPORATED/INC., CORPORATION/CORP., and LIMITED/LTD. For example,
“SHARPTOP DISTILLING CO.” supports “SHARPTOP DISTILLING COMPANY.” Cite the
visible label wording as evidence and set expected_value_found to true.

For producer_name_address specifically, inspect the name-and-address statement
separately. Treat the expected producer as located when the same business name
and city/state are visible, even if the label adds a phrase such as “Produced
by,” uses a logo, or omits punctuation, a street address, or a ZIP code. Do not
accept a different business name, city, or state.

For country_of_origin, extract the actual country named in a visible “Product
of,” “Made in,” or equivalent origin statement. Put only the country name in
value (for example, “Mexico”) and the complete visible phrase in evidence. If
the stated country differs from the application candidate, still return the
actual country value; do not return null merely because it differs.

For alcohol content, proof, and net contents, transcribe only what is visibly
present. Do not provide a compliance verdict.

Use exactly this object shape:
{
  "brand_name": {"value": string|null, "evidence": string|null, "expected_value_found": boolean|null, "confidence": 0..1},
  "class_type": {"value": string|null, "evidence": string|null, "expected_value_found": boolean|null, "confidence": 0..1},
  "alcohol_content": {"value": string|null, "evidence": string|null, "expected_value_found": null, "confidence": 0..1},
  "proof": {"value": string|null, "evidence": string|null, "expected_value_found": null, "confidence": 0..1},
  "net_contents": {"value": string|null, "evidence": string|null, "expected_value_found": null, "confidence": 0..1},
  "producer_name_address": {"value": string|null, "evidence": string|null, "expected_value_found": boolean|null, "confidence": 0..1},
  "country_of_origin": {"value": string|null, "evidence": string|null, "expected_value_found": boolean|null, "confidence": 0..1},
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

For government_warning, perform a lightweight presence check only: report the
short “GOVERNMENT WARNING:” heading in heading_text and evidence when visible.
Do not transcribe the body of the warning. Always return null for heading_bold;
the model must not judge capitalization, boldness, type size, legibility, or
placement. Those are human-review requirements, not automated screen results.

Keep alcohol_content and proof separate: alcohol_content must contain only the
percent alcohol-by-volume statement (for example, “40% Alc./Vol.”), while
proof must contain only the degrees-proof statement (for example, “80 Proof”).
Never use an ABV number as proof or a proof number as ABV. If one statement is
not confidently visible, return null for that field rather than copying the
other statement.
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

    def _request_extraction(self, content: list[dict], *, repair: bool) -> str:
        request_content = list(content)
        if repair:
            request_content.append(
                {
                    "type": "text",
                    "text": (
                        "Return the required JSON object only. Use null for any "
                        "uncertain value; do not add prose, markdown, or fields "
                        "outside the requested object."
                    ),
                }
            )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request_content},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=1800,
        )
        message = response.choices[0].message.content
        if not message:
            raise IndexError("The image service returned an empty response.")
        return message

    def extract(
        self,
        images: list[ImageInput],
        application: ApplicationData,
    ) -> LabelExtraction:
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
                    "Extract the requested evidence from these views of one "
                    "product label. Return one combined JSON object.\n\n"
                    "Expected text candidates to locate (these are search "
                    "targets, not text to repeat unless visible):\n"
                    f"- Beverage type: {application.beverage_type.replace('_', ' ')}\n"
                    f"- Brand name: {application.brand_name}\n"
                    f"- Class or type: {application.class_type}\n"
                    f"- Producer name and address: "
                    f"{application.producer_name_address}\n"
                    f"- Country of origin: "
                    f"{application.country_of_origin or 'Not applicable'}"
                ),
            }
        )

        try:
            invalid_response: Exception | None = None
            for repair in (False, True):
                try:
                    message = self._request_extraction(content, repair=repair)
                    return LabelExtraction.model_validate(json.loads(message))
                except (json.JSONDecodeError, ValidationError, IndexError) as exc:
                    invalid_response = exc
            assert invalid_response is not None
            raise ProviderError(
                "The image service returned an invalid result after a retry. Please retry."
            ) from invalid_response
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

    def extract(
        self,
        images: list[ImageInput],
        application: ApplicationData,
    ) -> LabelExtraction:
        return LabelExtraction(
            brand_name=ExtractedField(
                value="OLD TOM DISTILLERY",
                evidence="OLD TOM DISTILLERY",
                expected_value_found=True,
                confidence=0.99,
            ),
            class_type=ExtractedField(
                value="Kentucky Straight Bourbon Whiskey",
                evidence="Kentucky Straight Bourbon Whiskey",
                expected_value_found=True,
                confidence=0.98,
            ),
            alcohol_content=ExtractedField(
                value="45% Alc./Vol.",
                evidence="45% Alc./Vol.",
                confidence=0.99,
            ),
            proof=ExtractedField(
                value="90 Proof",
                evidence="90 Proof",
                confidence=0.99,
            ),
            net_contents=ExtractedField(
                value="750 mL", evidence="750 mL", confidence=0.99
            ),
            producer_name_address=ExtractedField(
                value="Old Tom Distillery, Louisville KY",
                evidence="Old Tom Distillery, Louisville KY",
                expected_value_found=True,
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
