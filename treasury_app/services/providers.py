"""Replaceable multimodal extraction providers."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from PIL import Image, ImageOps, UnidentifiedImageError
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

# MiMo performs its own vision preprocessing, so sending camera-resolution
# originals only adds upload and decode time. Controlled checks against the
# evidence corpus retained the requested fields at a 900 px longest edge while
# cutting a representative request from 643 KB to about 195 KB.
MAX_PROVIDER_IMAGE_EDGE = 900
MAX_PROVIDER_IMAGE_PIXELS = 16_000_000
PROVIDER_JPEG_QUALITY = 90
MAX_COMPLETION_TOKENS = 700


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
    field_value = _optional_text(value.get("value", value.get("v")))
    evidence = (
        _optional_text(value.get("evidence", value.get("e"))) or field_value
    )
    return {
        "value": field_value,
        "evidence": evidence,
        "expected_value_found": _optional_bool(
            value.get("expected_value_found", value.get("f"))
        ),
        "confidence": _confidence(value.get("confidence", value.get("c"))),
    }


def _warning_payload(value: object) -> dict:
    if not isinstance(value, dict):
        value = {}
    return {
        "verbatim_text": _optional_text(value.get("verbatim_text")),
        "heading_text": _optional_text(value.get("heading_text", value.get("h"))),
        "heading_bold": _optional_bool(value.get("heading_bold")),
        "legible": _optional_bool(value.get("legible")),
        "evidence": _optional_text(value.get("evidence", value.get("e"))),
        "confidence": _confidence(value.get("confidence", value.get("c"))),
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

    compact_fields = {
        "b": "brand_name",
        "y": "class_type",
        "a": "alcohol_content",
        "p": "proof",
        "n": "net_contents",
        "d": "producer_name_address",
        "o": "country_of_origin",
    }
    if not any(name in payload for name in EXTRACTED_FIELD_NAMES) and any(
        key in payload for key in (*compact_fields, "t", "w")
    ):
        payload = {
            "beverage_type": payload.get("t"),
            **{
                field_name: payload.get(short_name)
                for short_name, field_name in compact_fields.items()
            },
            "government_warning": payload.get("w"),
        }

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


def optimize_image_for_provider(image: ImageInput) -> ImageInput:
    """Shrink a label for transport while preserving the original on failure.

    Images above the provider edge limit are always resized. A smaller image is
    otherwise converted only when the JPEG is at least ten percent smaller than
    the upload, leaving already-efficient inputs byte-for-byte intact.
    """
    try:
        with Image.open(BytesIO(image.content)) as source:
            if source.width * source.height > MAX_PROVIDER_IMAGE_PIXELS:
                raise ProviderError(
                    "The label image dimensions are too large. Please resize the "
                    "image to 16 megapixels or less and retry."
                )
            prepared = ImageOps.exif_transpose(source)
            oriented_size = prepared.size
            prepared.thumbnail(
                (MAX_PROVIDER_IMAGE_EDGE, MAX_PROVIDER_IMAGE_EDGE),
                Image.Resampling.LANCZOS,
            )
            was_resized = prepared.size != oriented_size
            if "A" in prepared.getbands():
                rgba = prepared.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                prepared = rgb
            elif prepared.mode != "RGB":
                prepared = prepared.convert("RGB")

            output = BytesIO()
            prepared.save(
                output,
                format="JPEG",
                quality=PROVIDER_JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
            optimized = output.getvalue()
    except Image.DecompressionBombError as exc:
        raise ProviderError(
            "The label image dimensions are too large. Please resize the image "
            "to 16 megapixels or less and retry."
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError):
        logger.info(
            "Could not optimize %s; sending the validated original image.",
            image.filename,
        )
        return image

    if not was_resized and len(optimized) >= len(image.content) * 0.9:
        return image
    logger.info(
        "Optimized %s from %s to %s bytes for image review.",
        image.filename,
        len(image.content),
        len(optimized),
    )
    return ImageInput(
        content=optimized,
        mime_type="image/jpeg",
        filename=image.filename,
    )


SYSTEM_PROMPT = """
You extract evidence from United States alcohol beverage label artwork.
Return JSON only.

First infer only a broad beverage profile from the visible label: distilled
spirits, wine, malt beverage, or null. Do not map the product to a specific
TTB Product Class/Type code and do not make a commodity-specific compliance
decision. Use the broad profile only to interpret the requested evidence: proof
normally applies to distilled spirits, so return null for proof on wine and
malt beverage labels.

Return beverage_type as exactly `distilled_spirits`, `wine`, `malt_beverage`,
or null, then extract the most clearly visible value for each field. For a
label-only screen, no application candidates are supplied, so set
expected_value_found to null. Do not claim that a legal statement is absent or
noncompliant; return null when a value is not confidently visible.

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

Use only this compact JSON schema:
{"t": beverage_type, "b": field, "y": field, "a": numeric, "p": numeric,
 "n": numeric, "d": field, "o": field, "w": warning}
The keys mean t=beverage type, b=brand, y=class/type, a=ABV, p=proof, n=net
contents, d=producer/address, o=origin, and w=warning. A text field is
{"v": string|null, "f": boolean|null, "c": 0..1}; a numeric field is
{"v": string|null, "c": 0..1}; warning is {"h": string|null, "c": 0..1}.
An optional short "e" evidence string may be included only when it adds
information not already present in "v". Omit null-only optional keys and all
unrequested fields.

For w, perform a lightweight presence check only: report the short
“GOVERNMENT WARNING:” heading in h when visible. Do not transcribe the body or
return typography fields; the model must not judge capitalization, boldness,
type size, legibility, or placement. Those are human-review requirements, not
automated screen results.

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

Keep every value and evidence string under 120 characters. Do not repeat the
instructions, add prose, or return markdown.
""".strip()


# Quick scans do not need the expected-value matching rules above. Keeping a
# separate focused prompt saves several thousand input tokens for the workflow
# most likely to process many labels.
SCREEN_SYSTEM_PROMPT = """
Extract visible evidence from one United States alcohol-beverage label. Return
JSON only and never make an approval or compliance decision.

Infer beverage_type as exactly distilled_spirits, wine, malt_beverage, or null.
Transcribe clearly visible brand, class/type, alcohol by volume, proof (only for
distilled spirits), net contents, producer/importer name and address, and an
explicit country-of-origin statement. Use null rather than guessing. Keep ABV
and proof separate. A decimal comma is a decimal point, and a standalone e or
℮ after a metric volume is an estimated-quantity mark.

Use only this compact JSON schema:
{"t": beverage_type, "b": item, "y": item, "a": item, "p": item,
 "n": item, "d": item, "o": item, "w": warning}
The keys mean t=beverage type, b=brand, y=class/type, a=ABV, p=proof, n=net
contents, d=producer/address, o=origin, and w=warning. Each item is
{"v": string|null, "c": 0..1}; warning is {"h": string|null, "c": 0..1}.
An optional short "e" evidence string may be included only when it adds
information not already present in "v".

Only locate the short GOVERNMENT WARNING heading; do not transcribe the body or
judge wording, capitalization, boldness, size, legibility, or placement. Keep
every string under 120 characters. Do not add prose, markdown, raw OCR text,
notes, expected-value flags, null-only optional keys, or unrequested fields.
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
            # The UI already provides explicit per-label retry controls. An
            # invisible SDK retry can otherwise double latency and API cost.
            max_retries=0,
        )

    def _request_extraction(
        self,
        content: list[dict],
        *,
        system_prompt: str,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=MAX_COMPLETION_TOKENS,
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
            optimized = optimize_image_for_provider(image)
            encoded = base64.b64encode(optimized.content).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{optimized.mime_type};base64,{encoded}"
                    },
                }
            )
        return content

    def _extract_content(
        self,
        content: list[dict],
        *,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> LabelExtraction:
        try:
            message = self._request_extraction(content, system_prompt=system_prompt)
            return parse_extraction_response(message)
        except (json.JSONDecodeError, ValidationError, ValueError, IndexError) as exc:
            logger.warning(
                "MiMo returned an invalid extraction (%s).",
                type(exc).__name__,
            )
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

    def extract(
        self,
        images: list[ImageInput],
        application: ApplicationData,
    ) -> LabelExtraction:
        beverage_profile_target = (
            application.beverage_type.replace("_", " ")
            if application.beverage_type is not None
            else "Determine from the visible label"
        )
        content = self._image_content(images)
        content.append(
            {
                "type": "text",
                "text": (
                    "Extract the requested evidence from these views of one "
                    "product label. Return one combined JSON object.\n\n"
                    "Expected text candidates to locate (these are search "
                    "targets, not text to repeat unless visible):\n"
                    f"- Beverage profile: {beverage_profile_target}\n"
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
        return self._extract_content(content, system_prompt=SCREEN_SYSTEM_PROMPT)


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
