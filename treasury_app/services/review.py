"""Deterministic comparison rules for extracted label observations."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from treasury_app.models import (
    ApplicationData,
    ExtractedField,
    LabelExtraction,
    ReviewCheck,
    ReviewResult,
)

GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health problems."
)
MIN_CONFIDENCE = 0.75


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.casefold().replace("&", " and ")
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return " ".join(normalized.split())


def normalize_warning(value: str | None) -> str:
    return " ".join((value or "").split())


def parse_numbers(value: str | None) -> list[float]:
    return [float(number) for number in re.findall(r"\d+(?:\.\d+)?", value or "")]


def parse_abv(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*%\s*(?:alc(?:ohol)?\.?\s*/?\s*vol(?:ume)?\.?)?",
        value,
        re.IGNORECASE,
    )
    return float(match.group(1)) if match else None


def parse_proof(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*proof", value, re.IGNORECASE)
    return float(match.group(1)) if match else None


def parse_volume_ml(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(ml|millilit(?:er|re)s?|l|lit(?:er|re)s?)\b",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    return amount * 1000 if unit in {"l", "liter", "litre", "liters", "litres"} else amount


def compare_text(
    *,
    key: str,
    label: str,
    expected: str | None,
    field: ExtractedField,
    required: bool = True,
) -> ReviewCheck:
    if not expected and not required:
        return ReviewCheck(
            key=key,
            label=label,
            status="match",
            expected="Not applicable",
            observed=field.value,
            explanation="This field is not required for the supplied application.",
            evidence=field.evidence,
            confidence=field.confidence,
        )
    if not field.value:
        return ReviewCheck(
            key=key,
            label=label,
            status="review" if field.confidence < MIN_CONFIDENCE else "mismatch",
            expected=expected,
            observed=None,
            explanation="The field could not be read confidently from the label.",
            evidence=field.evidence,
            confidence=field.confidence,
        )

    expected_normalized = normalize_text(expected)
    observed_normalized = normalize_text(field.value)
    similarity = SequenceMatcher(
        None, expected_normalized, observed_normalized
    ).ratio()

    if expected_normalized == observed_normalized:
        status = "match"
        explanation = "The application and label match after harmless formatting normalization."
    elif similarity >= 0.86:
        status = "review"
        explanation = "The values are similar but require a reviewer to confirm the variation."
    else:
        status = "mismatch"
        explanation = "The application and label values do not match."

    if field.confidence < MIN_CONFIDENCE and status == "match":
        status = "review"
        explanation = "The value appears to match, but image-reading confidence is low."

    return ReviewCheck(
        key=key,
        label=label,
        status=status,
        expected=expected,
        observed=field.value,
        explanation=explanation,
        evidence=field.evidence,
        confidence=field.confidence,
    )


def numeric_check(
    *,
    key: str,
    label: str,
    expected: float,
    observed: float | None,
    observed_text: str | None,
    evidence: str | None,
    confidence: float,
    tolerance: float = 0.05,
) -> ReviewCheck:
    if observed is None:
        status = "review" if confidence < MIN_CONFIDENCE else "mismatch"
        explanation = "A comparable numeric value could not be read from the label."
    elif abs(expected - observed) <= tolerance:
        status = "match" if confidence >= MIN_CONFIDENCE else "review"
        explanation = (
            "The numeric value matches."
            if status == "match"
            else "The value appears to match, but image-reading confidence is low."
        )
    else:
        status = "mismatch"
        explanation = "The numeric value does not match the application."
    return ReviewCheck(
        key=key,
        label=label,
        status=status,
        expected=f"{expected:g}",
        observed=observed_text,
        explanation=explanation,
        evidence=evidence,
        confidence=confidence,
    )


def build_review(
    application: ApplicationData,
    extraction: LabelExtraction,
    *,
    provider_name: str,
) -> ReviewResult:
    checks = [
        compare_text(
            key="brand_name",
            label="Brand name",
            expected=application.brand_name,
            field=extraction.brand_name,
        ),
        compare_text(
            key="class_type",
            label="Class or type",
            expected=application.class_type,
            field=extraction.class_type,
        ),
        numeric_check(
            key="abv",
            label="Alcohol by volume",
            expected=application.abv,
            observed=parse_abv(extraction.alcohol_content.value),
            observed_text=extraction.alcohol_content.value,
            evidence=extraction.alcohol_content.evidence,
            confidence=extraction.alcohol_content.confidence,
        ),
    ]

    if application.proof is not None:
        checks.append(
            numeric_check(
                key="proof",
                label="Proof",
                expected=application.proof,
                observed=parse_proof(extraction.alcohol_content.value),
                observed_text=extraction.alcohol_content.value,
                evidence=extraction.alcohol_content.evidence,
                confidence=extraction.alcohol_content.confidence,
                tolerance=0.1,
            )
        )

    expected_volume = parse_volume_ml(application.net_contents)
    observed_volume = parse_volume_ml(extraction.net_contents.value)
    if expected_volume is None:
        volume_check = ReviewCheck(
            key="net_contents",
            label="Net contents",
            status="review",
            expected=application.net_contents,
            observed=extraction.net_contents.value,
            explanation="The application volume could not be normalized.",
            evidence=extraction.net_contents.evidence,
            confidence=extraction.net_contents.confidence,
        )
    else:
        volume_check = numeric_check(
            key="net_contents",
            label="Net contents",
            expected=expected_volume,
            observed=observed_volume,
            observed_text=extraction.net_contents.value,
            evidence=extraction.net_contents.evidence,
            confidence=extraction.net_contents.confidence,
            tolerance=0.5,
        )
        volume_check.expected = application.net_contents
    checks.append(volume_check)

    checks.extend(
        [
            compare_text(
                key="producer",
                label="Producer name and address",
                expected=application.producer_name_address,
                field=extraction.producer_name_address,
            ),
            compare_text(
                key="country_of_origin",
                label="Country of origin",
                expected=application.country_of_origin,
                field=extraction.country_of_origin,
                required=bool(application.country_of_origin),
            ),
        ]
    )

    warning = extraction.government_warning
    warning_text_matches = normalize_warning(warning.verbatim_text) == GOVERNMENT_WARNING
    if not warning.verbatim_text:
        warning_status = "review" if warning.confidence < MIN_CONFIDENCE else "mismatch"
        warning_explanation = "The mandatory warning could not be read from the label."
    elif not warning_text_matches:
        warning_status = "mismatch"
        warning_explanation = "The warning wording or punctuation is not an exact match."
    elif warning.heading_text != "GOVERNMENT WARNING:":
        warning_status = "mismatch"
        warning_explanation = "The warning heading is not the required uppercase wording."
    elif warning.heading_bold is False:
        warning_status = "mismatch"
        warning_explanation = "The warning heading does not appear bold."
    elif warning.heading_bold is None or warning.legible is not True:
        warning_status = "review"
        warning_explanation = "The wording matches, but formatting or legibility is uncertain."
    elif warning.confidence < MIN_CONFIDENCE:
        warning_status = "review"
        warning_explanation = "The warning appears correct, but image-reading confidence is low."
    else:
        warning_status = "match"
        warning_explanation = "The warning wording and observable heading format match."

    checks.append(
        ReviewCheck(
            key="government_warning",
            label="Government warning",
            status=warning_status,
            expected=GOVERNMENT_WARNING,
            observed=warning.verbatim_text,
            explanation=warning_explanation,
            evidence=warning.evidence,
            confidence=warning.confidence,
        )
    )

    statuses = {check.status for check in checks}
    if "mismatch" in statuses:
        overall_status = "attention"
        summary = "One or more fields need attention before this application can proceed."
    elif "review" in statuses:
        overall_status = "unable"
        summary = "No definite mismatch was found, but a reviewer must confirm uncertain evidence."
    else:
        overall_status = "match"
        summary = "All automated comparisons match the supplied application."

    return ReviewResult(
        application_id=application.application_id,
        overall_status=overall_status,
        summary=summary,
        checks=checks,
        notes=extraction.notes,
        provider=provider_name,
    )
