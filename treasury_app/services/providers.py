"""Replaceable multimodal extraction providers."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from treasury_app.models import (
    ApplicationData,
    BeverageType,
    ExtractedField,
    LabelExtraction,
    WarningObservation,
)


class ProviderError(RuntimeError):
    """Safe, user-facing provider failure."""


logger = logging.getLogger(__name__)

EXTRACTED_FIELD_NAMES = (
    "brand_name",
    "class_type",
    "alcohol_content",
    "proof",
    "net_contents",
    "producer_name_address",
    "country_of_origin",
)


def _beverage_type(value: object) -> BeverageType | None:
    if not isinstance(value, str):
        return None
    aliases: dict[str, BeverageType] = {
        "distilled_spirits": "distilled_spirits",
        "distilled spirits": "distilled_spirits",
        "spirits": "distilled_spirits",
        "wine": "wine",
        "malt_beverage": "malt_beverage",
        "malt beverage": "malt_beverage",
        "beer": "malt_beverage",
    }
    return aliases.get(value.strip().casefold())


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes"}:
            return True
        if normalized in {"false", "no"}:
            return False
    return None


def _confidence(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        number = float(str(value).strip().removesuffix("%"))
    except ValueError:
        return 0
    if number > 1 and number <= 100:
        number /= 100
    return min(1, max(0, number))


def _field_payload(value: object) -> dict:
    if isinstance(value, str):
        value = {"value": value}
    if not isinstance(value, dict):
        value = {}
    return {
        "value": _optional_text(value.get("value")),
        "evidence": _optional_text(value.get("evidence")),
        "expected_value_found": _optional_bool(value.get("expected_value_found")),
        "confidence": _confidence(value.get("confidence")),
    }


def _warning_payload(value: object) -> dict:
    if not isinstance(value, dict):
        value = {}
    return {
        "verbatim_text": _optional_text(value.get("verbatim_text")),
        "heading_text": _optional_text(value.get("heading_text")),
        "heading_bold": _optional_bool(value.get("heading_bold")),
        "legible": _optional_bool(value.get("legible")),
        "evidence": _optional_text(value.get("evidence")),
        "confidence": _confidence(value.get("confidence")),
    }


def parse_extraction_response(message: str) -> LabelExtraction:
    """Recover a safe extraction from common model JSON formatting mistakes."""
    candidate = message.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        candidate,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(candidate[start : end + 1])

    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError("The extraction response must be a JSON object.")

    if not any(name in payload for name in EXTRACTED_FIELD_NAMES):
        for wrapper in ("result", "extraction", "label_extraction"):
            nested = payload.get(wrapper)
            if isinstance(nested, dict):
                payload = nested
                break

    notes = payload.get("notes")
    if isinstance(notes, str):
        notes = [notes]
    elif isinstance(notes, list):
        notes = [note for note in (_optional_text(item) for item in notes) if note]
    else:
        notes = []

    normalized = {
        name: _field_payload(payload.get(name)) for name in EXTRACTED_FIELD_NAMES
    }
    normalized.update(
        {
            "beverage_type": _beverage_type(payload.get("beverage_type")),
            "government_warning": _warning_payload(payload.get("government_warning")),
            "raw_text": _optional_text(payload.get("raw_text")),
            "notes": notes,
        }
    )
    return LabelExtraction.model_validate(normalized)


class ExtractionProvider(Protocol):
    name: str

    def extract(
        self,
        images: list["ImageInput"],
        application: ApplicationData,
    ) -> LabelExtraction:
        """Extract structured observations from label images."""

    def screen(self, images: list["ImageInput"]) -> LabelExtraction:
        """Extract label-only observations without application data."""


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

For a label-only screen, no application candidates are supplied. Identify the
beverage_type as exactly `distilled_spirits`, `wine`, `malt_beverage`, or null,
then extract the most clearly visible value for each field. Set
expected_value_found to null in this mode. Do not claim that a legal statement
is absent or noncompliant; return null when a value is not confidently visible.

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

Country statements may use a local-language country name. Treat a translated
country name as the same country for the expected-value check: for example,
“Italia” supports “Italy”, “España” supports “Spain”, and “Deutschland”
supports “Germany”. Do not use a city, region, or a producer-address line by
itself as a country-of-origin statement.

For alcohol content, proof, and net contents, transcribe only what is visibly
present. Do not provide a compliance verdict.

Use exactly this object shape:
{
  "beverage_type": "distilled_spirits"|"wine"|"malt_beverage"|null,
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

For numeric statements, preserve the wording exactly as it appears. A decimal
comma is equivalent to a decimal point (for example, “12,5% vol.” means 12.5%
ABV). For metric net contents, a trailing standalone `e` or `℮` is the
estimated-quantity mark, not part of the volume (for example, “1,5 l e” means
1.5 L). Do not treat either notation as a discrepancy.
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
                        "The prior response could not be parsed. Return the required "
                        "JSON object only. Keep every value and evidence string under "
                        "120 characters, set raw_text to null and notes to [], use null "
                        "for uncertain values, and use confidence numbers from 0 to 1. "
                        "Do not add prose, markdown, or unrequested fields."
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
            max_completion_tokens=2400,
            temperature=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise IndexError("The image service response was truncated.")
        message = choice.message.content
        if not message:
            raise IndexError("The image service returned an empty response.")
        return message

    def _image_content(self, images: list[ImageInput]) -> list[dict]:
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
        return content

    def _extract_content(self, content: list[dict]) -> LabelExtraction:
        try:
            invalid_response: Exception | None = None
            for attempt, repair in enumerate((False, True), start=1):
                try:
                    message = self._request_extraction(content, repair=repair)
                    return parse_extraction_response(message)
                except (json.JSONDecodeError, ValidationError, ValueError, IndexError) as exc:
                    invalid_response = exc
                    logger.warning(
                        "MiMo returned an invalid extraction on attempt %s (%s).",
                        attempt,
                        type(exc).__name__,
                    )
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

    def extract(
        self,
        images: list[ImageInput],
        application: ApplicationData,
    ) -> LabelExtraction:
        content = self._image_content(images)
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
        return self._extract_content(content)

    def screen(self, images: list[ImageInput]) -> LabelExtraction:
        content = self._image_content(images)
        content.append(
            {
                "type": "text",
                "text": (
                    "Screen this single alcohol-beverage label without application "
                    "data. Identify the beverage profile and transcribe only clearly "
                    "visible common label information. Return null for anything that "
                    "is not confidently visible; do not make a compliance decision."
                ),
            }
        )
        return self._extract_content(content)


class MockProvider:
    name = "Mock provider"

    def extract(
        self,
        images: list[ImageInput],
        application: ApplicationData,
    ) -> LabelExtraction:
        return LabelExtraction(
            beverage_type="distilled_spirits",
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

    def screen(self, images: list[ImageInput]) -> LabelExtraction:
        return self.extract(
            images,
            ApplicationData(
                brand_name="Old Tom Distillery",
                class_type="Kentucky Straight Bourbon Whiskey",
                abv=45,
                net_contents="750 mL",
                producer_name_address="Old Tom Distillery, Louisville KY",
            ),
        )
