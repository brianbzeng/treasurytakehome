"""Deterministic comparison rules for extracted label observations."""

from __future__ import annotations

import re
import unicodedata

from treasury_app.models import (
    ApplicationData,
    BeverageType,
    ExtractedField,
    LabelExtraction,
    LabelScreenResult,
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

PROFILE_GUIDANCE: dict[BeverageType, dict[str, tuple[str, str, str]]] = {
    "distilled_spirits": GUIDANCE_REFERENCES,
    "wine": {
        "brand_name": (
            "TTB: Wine labeling guidance",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/wine/labeling-wine",
            "TTB's wine-labeling overview covers brand names, class/type designations, name and address, and other required label information.",
        ),
        "class_type": (
            "TTB: Wine mandatory-label checklist",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/wine/labeling-wine/wine-labeling-checklist-of-mandatory-label-information",
            "Use TTB's checklist to verify the required wine class or type designation and related mandatory information.",
        ),
        "abv": (
            "TTB: Wine alcohol content",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/wine/wine-labeling-alcohol-content",
            "Wine alcohol-content requirements vary by the product's alcohol level and class/type designation.",
        ),
        "net_contents": (
            "TTB: Wine net contents",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/wine/labeling-wine/wine-labeling-net-contents",
            "TTB's wine net-contents guidance covers metric declarations, placement, and standards of fill.",
        ),
        "producer": (
            "TTB: Wine mandatory-label checklist",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/wine/labeling-wine/wine-labeling-checklist-of-mandatory-label-information",
            "The checklist includes the required name-and-address statement for wine labels.",
        ),
        "country_of_origin": (
            "TTB: Importing alcohol beverages",
            "https://www.ttb.gov/images/pdfs/importing-alcohol-beverages-october-2022.pdf",
            "TTB's import guide identifies country-of-origin labeling as a required item for imported alcohol beverages.",
        ),
        "government_warning": (
            "TTB: Wine mandatory-label checklist",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/wine/labeling-wine/wine-labeling-checklist-of-mandatory-label-information",
            "TTB's wine checklist includes the health warning statement among the mandatory label information.",
        ),
    },
    "malt_beverage": {
        "brand_name": (
            "TTB: Malt beverage mandatory label information",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/beer/labeling/malt-beverage-mandatory-label-information",
            "TTB identifies the brand name as a mandatory statement for malt beverage labels.",
        ),
        "class_type": (
            "TTB: Malt beverage class and type designation",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/beer/labeling/malt-beverage-class-and-type",
            "TTB explains required malt beverage class/type designations and specialty-product statements of composition.",
        ),
        "abv": (
            "TTB: Malt beverage alcohol content",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/beer/labeling/malt-beverage-alcohol-content",
            "For malt beverages, TTB requires or permits alcohol-content statements under circumstances described in this guidance.",
        ),
        "net_contents": (
            "TTB: Malt beverage net contents",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/beer/labeling/malt-beverage-net-contents",
            "TTB's malt-beverage net-contents guidance explains the required U.S. standard measures and acceptable metric equivalents.",
        ),
        "producer": (
            "TTB: Malt beverage mandatory label information",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/beer/labeling/malt-beverage-mandatory-label-information",
            "TTB identifies the domestic/import name-and-address statement as mandatory malt beverage label information.",
        ),
        "country_of_origin": (
            "TTB: Importing alcohol beverages",
            "https://www.ttb.gov/images/pdfs/importing-alcohol-beverages-october-2022.pdf",
            "TTB's import guide identifies country-of-origin labeling as a required item for imported alcohol beverages.",
        ),
        "government_warning": (
            "TTB: Anatomy of a malt beverage label",
            "https://www.ttb.gov/regulated-commodities/beverage-alcohol/beer/labeling/anatomy-of-a-malt-beverage-label-tool",
            "TTB's label tool identifies the health warning statement as required for applicable alcoholic beverages.",
        ),
    },
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.casefold().replace("&", " and ")
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return " ".join(normalized.split())


def normalize_business_name(value: str | None) -> str:
    """Normalize common legal-entity suffix variants for evidence matching."""
    suffixes = {
        "co": "company",
        "inc": "incorporated",
        "corp": "corporation",
        "ltd": "limited",
    }
    return " ".join(suffixes.get(word, word) for word in normalize_text(value).split())


def normalize_country(value: str | None) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"^(?:product|made|produced) of ", "", normalized)
    aliases = {
        "us": "united states",
        "usa": "united states",
        "united states of america": "united states",
        "italia": "italy",
        "italien": "italy",
        "espana": "spain",
        "espagne": "spain",
        "deutschland": "germany",
        "allemagne": "germany",
        "portogallo": "portugal",
        "portugal": "portugal",
        "italy": "italy",
        "spain": "spain",
        "germany": "germany",
        "france": "france",
    }
    if normalized in aliases:
        return aliases[normalized]
    # Image extraction occasionally returns the full origin line instead of only
    # the country. Recognize a country term in that line while keeping a city or
    # region alone from being treated as a country-of-origin match.
    for term, canonical in aliases.items():
        if re.search(rf"\b{re.escape(term)}\b", normalized):
            return canonical
    return normalized


def normalize_warning(value: str | None) -> str:
    return " ".join((value or "").split())


def parse_numbers(value: str | None) -> list[float]:
    return [
        float(number.replace(",", "."))
        for number in re.findall(r"\d+(?:[.,]\d+)?", value or "")
    ]


def parse_abv(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*%\s*(?:alc(?:ohol)?\.?\s*/?\s*vol(?:ume)?\.?)?",
        value,
        re.IGNORECASE,
    )
    return float(match.group(1).replace(",", ".")) if match else None


def parse_proof(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*proof", value, re.IGNORECASE)
    return float(match.group(1).replace(",", ".")) if match else None


def parse_volume_ml(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(fl(?:uid)?\.?\s*oz(?:\.|s)?|fluid ounces?|"
        r"pints?|pts?\.?|quarts?|qts?\.?|gallons?|gals?\.?|ml|"
        r"millilit(?:er|re)s?|cl|centilit(?:er|re)s?|l|lit(?:er|re)s?)\b",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    unit = re.sub(r"[.\s]", "", match.group(2).lower())
    factors_ml = {
        "ml": 1,
        "milliliter": 1,
        "milliliters": 1,
        "millilitre": 1,
        "millilitres": 1,
        "cl": 10,
        "centiliter": 10,
        "centiliters": 10,
        "centilitre": 10,
        "centilitres": 10,
        "l": 1000,
        "liter": 1000,
        "liters": 1000,
        "litre": 1000,
        "litres": 1000,
        "floz": 29.5735295625,
        "fluidounce": 29.5735295625,
        "fluidounces": 29.5735295625,
        "pint": 473.176473,
        "pints": 473.176473,
        "pt": 473.176473,
        "pts": 473.176473,
        "quart": 946.352946,
        "quarts": 946.352946,
        "qt": 946.352946,
        "qts": 946.352946,
        "gallon": 3785.411784,
        "gallons": 3785.411784,
        "gal": 3785.411784,
        "gals": 3785.411784,
    }
    return amount * factors_ml[unit]


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
    observed_evidence = field.evidence or field.value
    business_name_matches = (
        key in {"brand_name", "producer"}
        and bool(field.value)
        and normalize_business_name(expected) == normalize_business_name(field.value)
    )
    if observed_evidence and (field.expected_value_found is True or business_name_matches):
        return ReviewCheck(
            key=key,
            label=label,
            status="match" if field.confidence >= MIN_CONFIDENCE else "review",
            expected=expected,
            observed=observed_evidence,
            explanation=(
                "The expected application value was located in the visible label text."
                if field.confidence >= MIN_CONFIDENCE
                else "The expected application value may be visible, but the image-reading confidence is low."
            ),
            evidence=observed_evidence,
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


def compare_country(*, expected: str | None, field: ExtractedField) -> ReviewCheck:
    if not expected:
        return ReviewCheck(
            key="country_of_origin",
            label="Country of origin",
            status="match",
            expected="Not applicable",
            observed=field.value,
            explanation="This field is not required for the supplied application.",
            evidence=field.evidence,
            confidence=field.confidence,
        )

    observed = field.evidence or field.value
    if not field.value:
        return ReviewCheck(
            key="country_of_origin",
            label="Country of origin",
            status="review",
            expected=expected,
            observed="Not confidently located",
            explanation=(
                "The country-of-origin statement was not confidently located in the "
                "label artwork. This requires reviewer confirmation."
            ),
            evidence=field.evidence,
            confidence=field.confidence,
        )

    if normalize_country(expected) == normalize_country(field.value):
        status = "match" if field.confidence >= MIN_CONFIDENCE else "review"
        explanation = (
            "The country-of-origin statement matches the application."
            if status == "match"
            else "The country appears to match, but image-reading confidence is low."
        )
    else:
        status = "mismatch" if field.confidence >= MIN_CONFIDENCE else "review"
        explanation = (
            "The country-of-origin statement does not match the application."
            if status == "mismatch"
            else "The country may differ, but image-reading confidence is low."
        )
    return ReviewCheck(
        key="country_of_origin",
        label="Country of origin",
        status=status,
        expected=expected,
        observed=observed,
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


def attach_guidance(check: ReviewCheck, beverage_type: BeverageType) -> None:
    """Add a focused official reference to a check, when one is available."""
    reference = PROFILE_GUIDANCE[beverage_type].get(check.key)
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
    ]
    beverage_type = application.beverage_type or extraction.beverage_type

    if application.abv is not None:
        checks.append(
            numeric_check(
                key="abv",
                label="Alcohol by volume",
                expected=application.abv,
                observed=parse_abv(extraction.alcohol_content.value),
                observed_text=extraction.alcohol_content.value,
                evidence=extraction.alcohol_content.evidence,
                confidence=extraction.alcohol_content.confidence,
            )
        )
    elif beverage_type == "distilled_spirits":
        checks.append(
            ReviewCheck(
                key="abv",
                label="Alcohol by volume",
                status="review",
                expected="Not supplied",
                observed=extraction.alcohol_content.value or "Not confidently read",
                explanation=(
                    "The label was inferred to be a distilled-spirit product, but no "
                    "submitted ABV was available for comparison."
                ),
                evidence=extraction.alcohol_content.evidence,
                confidence=extraction.alcohol_content.confidence,
            )
        )

    if application.proof is not None and beverage_type not in {"malt_beverage", "wine"}:
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
            label="Total bottle capacity",
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
            label="Total bottle capacity",
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
                label="Name and address of applicant",
                expected=application.producer_name_address,
                field=extraction.producer_name_address,
            ),
            compare_country(
                expected=application.country_of_origin,
                field=extraction.country_of_origin,
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

    if beverage_type is not None:
        for check in checks:
            attach_guidance(check, beverage_type)

    statuses = {check.status for check in checks}
    comparison_statuses = {
        check.status for check in checks if check.key != "government_warning"
    }
    if "mismatch" in statuses:
        overall_status = "attention"
        summary = (
            "The automated screen found one or more differences. "
            "A reviewer must verify the label and applicable requirements before acting."
        )
    elif "review" in comparison_statuses:
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


def screen_presence_check(
    *,
    key: str,
    label: str,
    field: ExtractedField,
    required_for_screen: bool,
) -> ReviewCheck:
    """Report visible evidence without claiming a legal compliance conclusion."""
    observed = field.evidence or field.value
    if observed:
        status = "match" if field.confidence >= MIN_CONFIDENCE else "review"
        explanation = (
            "A visible value was located on the label."
            if status == "match"
            else "A possible value was located, but image-reading confidence is low."
        )
        return ReviewCheck(
            key=key,
            label=label,
            status=status,
            expected=None,
            observed=observed,
            explanation=explanation,
            evidence=field.evidence,
            confidence=field.confidence,
        )

    if required_for_screen:
        return ReviewCheck(
            key=key,
            label=label,
            status="review",
            expected=None,
            observed="Not confidently located",
            explanation=(
                "This common label statement was not confidently located. "
                "Verify whether it is required and present before acting."
            ),
            evidence=field.evidence,
            confidence=field.confidence,
        )

    return ReviewCheck(
        key=key,
        label=label,
        status="match",
        expected=None,
        observed="Not assessed",
        explanation="This item is not automatically screened as required for this label.",
        evidence=field.evidence,
        confidence=field.confidence,
    )


def build_label_screen(
    label_id: str,
    extraction: LabelExtraction,
    *,
    provider_name: str,
) -> LabelScreenResult:
    """Build cautious, label-only screening results with no application comparison."""
    beverage_type = extraction.beverage_type
    checks = [
        screen_presence_check(
            key="brand_name",
            label="Brand name",
            field=extraction.brand_name,
            required_for_screen=True,
        ),
        screen_presence_check(
            key="class_type",
            label="Class or type designation",
            field=extraction.class_type,
            required_for_screen=True,
        ),
        screen_presence_check(
            key="abv",
            label="Alcohol by volume",
            field=extraction.alcohol_content,
            required_for_screen=beverage_type == "distilled_spirits",
        ),
        screen_presence_check(
            key="proof",
            label="Proof",
            field=extraction.proof,
            required_for_screen=False,
        ),
        screen_presence_check(
            key="net_contents",
            label="Total bottle capacity",
            field=extraction.net_contents,
            required_for_screen=True,
        ),
        screen_presence_check(
            key="producer",
            label="Producer, bottler, or importer statement",
            field=extraction.producer_name_address,
            required_for_screen=True,
        ),
        screen_presence_check(
            key="country_of_origin",
            label="Country of origin",
            field=extraction.country_of_origin,
            required_for_screen=False,
        ),
    ]

    warning = extraction.government_warning
    warning_source = " ".join(
        part for part in (warning.heading_text, warning.verbatim_text, warning.evidence) if part
    )
    warning_detected = bool(
        re.search(r"\bgovernment\s+warning\b", warning_source, re.IGNORECASE)
    )
    checks.append(
        ReviewCheck(
            key="government_warning",
            label="Government warning",
            status="match" if warning_detected else "review",
            expected=None,
            observed=(
                "Government warning heading detected."
                if warning_detected
                else "Not confidently located"
            ),
            explanation=(
                "The warning heading was located. Typography, wording, placement, and "
                "legibility remain human-review items."
                if warning_detected
                else "The warning heading was not confidently located. Verify whether it is "
                "required and present before acting."
            ),
            evidence=warning.evidence,
            confidence=warning.confidence,
        )
    )

    if beverage_type is not None:
        for check in checks:
            attach_guidance(check, beverage_type)

    has_review_items = any(check.status == "review" for check in checks)
    if has_review_items:
        overall_status = "attention"
        summary = (
            "The automated screen found one or more possible review items. "
            "Verify the label artwork and applicable requirements before acting."
        )
    else:
        overall_status = "match"
        summary = (
            "The automated screen did not identify a major visible review item. "
            "This limited diagnostic is not an approval or final determination."
        )

    return LabelScreenResult(
        label_id=label_id,
        beverage_type=beverage_type,
        overall_status=overall_status,
        summary=summary,
        checks=checks,
        notes=extraction.notes,
        provider=provider_name,
    )
