"""Deterministic comparison rules for extracted label observations."""

from __future__ import annotations

import re
import unicodedata

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
WARNING_EXPECTATION = (
    "Government warning heading should be visible; typography requires human verification."
)

# These links lead to the TTB guidance page that discusses the particular
# label statement, rather than to a generic help page.  The UI only exposes a
# reference when the automated screen has not matched the corresponding check.
GUIDANCE_REFERENCES: dict[str, tuple[str, str, str]] = {
    "brand_name": (
        "TTB: Brand name — including brand vs. fanciful names",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/ds-brand-name",
        "TTB distinguishes the required brand name from an optional distinctive or fanciful name; an optional name does not replace the brand name.",
    ),
    "class_type": (
        "TTB: Class, type, and fanciful-name designations",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/anatomy-of-a-distilled-spirits-label-tool",
        "The Class, Type, or Other Designation section explains when a class/type statement is required and when a specialty product may use a fanciful name with a statement of composition.",
    ),
    "abv": (
        "TTB: Alcohol content statement requirements",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/ds-alcohol-content",
        "TTB describes the required percentage-alcohol-by-volume statement and how an optional proof statement may be shown with it.",
    ),
    "proof": (
        "TTB: Alcohol content statement requirements",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/ds-alcohol-content",
        "TTB describes the required percentage-alcohol-by-volume statement and how an optional proof statement may be shown with it.",
    ),
    "net_contents": (
        "TTB: Net contents — metric statement and container sizes",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/ds-net-contents",
        "This TTB page covers the net-contents statement, permitted metric forms, placement, and the current standards of fill.",
    ),
    "producer": (
        "TTB: Name and address — bottler, distiller, or importer",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/ds-name-address",
        "TTB explains the required explanatory phrase and the name-and-address rules for domestic bottlers, distillers, and importers.",
    ),
    "country_of_origin": (
        "TTB Ruling 2001-2: Country of origin for imported spirits",
        "https://www.ttb.gov/images/pdfs/rulings/2001-2.htm",
        "For imported distilled spirits, the ruling explains the country-of-origin statement, including the customary “Product of …” form.",
    ),
    "government_warning": (
        "TTB: Health warning statement — text, placement, and formatting",
        "https://www.ttb.gov/regulated-commodities/beverage-alcohol/"
        "distilled-spirits/ds-labeling-home/ds-health-warning",
        "TTB provides the required wording and the requirements for the uppercase, bold heading, legibility, placement, and type size.",
    ),
}


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
    if field.expected_value_found is True and field.evidence:
        return ReviewCheck(
            key=key,
            label=label,
            status="match" if field.confidence >= MIN_CONFIDENCE else "review",
            expected=expected,
            observed=field.evidence,
            explanation=(
                "The expected application value was located in the visible label text."
                if field.confidence >= MIN_CONFIDENCE
                else "The expected application value may be visible, but the image-reading confidence is low."
            ),
            evidence=field.evidence,
            confidence=field.confidence,
        )

    return ReviewCheck(
        key=key,
        label=label,
        status="review",
        expected=expected,
        observed="Not confidently located",
        explanation=(
            "The expected application value was not confidently located in the label artwork. "
            "This is a possible review item, not proof that the value is absent or incorrect."
        ),
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
        status = "review"
        explanation = (
            "A comparable numeric value was not confidently read from the label. "
            "This requires reviewer confirmation rather than a mismatch finding."
        )
        observed_display = "Not confidently read"
    elif abs(expected - observed) <= tolerance:
        status = "match" if confidence >= MIN_CONFIDENCE else "review"
        explanation = (
            "The numeric value matches."
            if status == "match"
            else "The value appears to match, but image-reading confidence is low."
        )
        observed_display = observed_text
    else:
        status = "mismatch"
        explanation = "The numeric value does not match the application."
        observed_display = observed_text
    return ReviewCheck(
        key=key,
        label=label,
        status=status,
        expected=f"{expected:g}",
        observed=observed_display,
        explanation=explanation,
        evidence=evidence,
        confidence=confidence,
    )


def attach_guidance(check: ReviewCheck) -> None:
    """Add a focused official reference to a check, when one is available."""
    reference = GUIDANCE_REFERENCES.get(check.key)
    if reference is None:
        return
    check.guidance_title, check.guidance_url, check.guidance_summary = reference


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
                observed=parse_proof(extraction.proof.value),
                observed_text=extraction.proof.value,
                evidence=extraction.proof.evidence,
                confidence=extraction.proof.confidence,
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
    warning_source = " ".join(
        part for part in (warning.heading_text, warning.verbatim_text, warning.evidence) if part
    )
    heading_detected = bool(
        re.search(r"\bgovernment\s+warning\b", warning_source, re.IGNORECASE)
    )
    if heading_detected:
        warning_status = "match"
        warning_explanation = (
            "The warning heading was located. This automated screen does not verify "
            "the exact warning wording, capitalization, boldness, type size, "
            "legibility, or placement; those remain human-review items."
        )
        warning_observed = "Government warning heading detected."
    else:
        warning_status = "review"
        warning_explanation = (
            "The government-warning heading was not confidently located. A reviewer "
            "should confirm that the required statement is present and properly formatted."
        )
        warning_observed = "Government warning heading not confidently located."

    checks.append(
        ReviewCheck(
            key="government_warning",
            label="Government warning",
            status=warning_status,
            expected=WARNING_EXPECTATION,
            observed=warning_observed,
            explanation=warning_explanation,
            evidence=warning.evidence,
            confidence=warning.confidence,
        )
    )

    for check in checks:
        attach_guidance(check)

    statuses = {check.status for check in checks}
    if "mismatch" in statuses:
        overall_status = "attention"
        summary = (
            "The automated screen found one or more differences. "
            "A reviewer must verify the label and applicable requirements before acting."
        )
    elif "review" in statuses:
        overall_status = "unable"
        summary = (
            "The automated screen could not verify one or more fields. "
            "A reviewer should inspect the label and applicable requirements."
        )
    else:
        overall_status = "match"
        summary = (
            "No discrepancies were identified between the supplied application "
            "values and the label evidence. "
            "This is not an approval or final determination."
        )

    return ReviewResult(
        application_id=application.application_id,
        overall_status=overall_status,
        summary=summary,
        checks=checks,
        notes=extraction.notes,
        provider=provider_name,
    )
