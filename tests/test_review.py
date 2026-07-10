from treasury_app.models import ApplicationData, ExtractedField, LabelExtraction
from treasury_app.services.providers import MockProvider
from treasury_app.services.review import (
    GOVERNMENT_WARNING,
    build_review,
    normalize_business_name,
    normalize_country,
    normalize_text,
    parse_abv,
    parse_proof,
    parse_volume_ml,
)


def sample_application(**overrides):
    values = {
        "application_id": "APP-001",
        "brand_name": "Old Tom Distillery",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "abv": 45,
        "proof": 90,
        "net_contents": "750 mL",
        "producer_name_address": "Old Tom Distillery, Louisville KY",
        "country_of_origin": None,
    }
    values.update(overrides)
    return ApplicationData(**values)


def mock_extraction():
    return MockProvider().extract([], sample_application())


def test_normalization_handles_case_and_punctuation():
    assert normalize_text("STONE'S THROW") == normalize_text("Stone’s Throw")
    assert normalize_business_name("Sharptop Distilling Co.") == normalize_business_name(
        "SHARPTOP DISTILLING COMPANY"
    )
    assert normalize_country("Product of Mexico") == "mexico"
    assert normalize_country("USA") == "united states"


def test_brand_company_suffix_variant_is_matching_evidence():
    extraction = mock_extraction()
    extraction.brand_name = ExtractedField(
        value="SHARPTOP DISTILLING CO.",
        evidence="BOTTLED BY: SHARPTOP DISTILLING CO.",
        expected_value_found=False,
        confidence=0.99,
    )
    result = build_review(
        sample_application(brand_name="SHARPTOP DISTILLING COMPANY"),
        extraction,
        provider_name="Mock provider",
    )
    brand = next(check for check in result.checks if check.key == "brand_name")
    assert brand.status == "match"
    assert brand.observed == "BOTTLED BY: SHARPTOP DISTILLING CO."


def test_numeric_parsers():
    label = "45% Alc./Vol. (90 Proof)"
    assert parse_abv(label) == 45
    assert parse_proof(label) == 90
    assert parse_volume_ml("0.75 L") == 750
    assert parse_volume_ml("750 milliliters") == 750


def test_matching_extraction_passes_all_checks():
    result = build_review(
        sample_application(),
        mock_extraction(),
        provider_name="Mock provider",
    )
    assert result.overall_status == "match"
    assert "not an approval" in result.summary.lower()
    assert "no discrepancies" in result.summary.lower()
    assert all(check.status == "match" for check in result.checks)


def test_wine_profile_allows_an_omitted_abv_and_uses_wine_guidance():
    application = sample_application(
        beverage_type="wine",
        abv=None,
        proof=None,
        class_type="Red Wine",
    )
    result = build_review(
        application,
        mock_extraction(),
        provider_name="Mock provider",
    )
    assert result.overall_status == "match"
    assert "abv" not in {check.key for check in result.checks}
    assert "proof" not in {check.key for check in result.checks}
    net_contents = next(check for check in result.checks if check.key == "net_contents")
    assert "wine" in net_contents.guidance_title.lower()


def test_malt_beverage_profile_skips_proof_and_uses_malt_guidance():
    application = sample_application(
        beverage_type="malt_beverage",
        proof=80,
        class_type="India Pale Ale",
    )
    result = build_review(
        application,
        mock_extraction(),
        provider_name="Mock provider",
    )
    assert "proof" not in {check.key for check in result.checks}
    class_type = next(check for check in result.checks if check.key == "class_type")
    assert "malt beverage" in class_type.guidance_title.lower()


def test_abv_difference_requires_attention():
    result = build_review(
        sample_application(abv=40),
        mock_extraction(),
        provider_name="Mock provider",
    )
    assert result.overall_status == "attention"
    assert "differences" in result.summary.lower()
    abv_check = next(check for check in result.checks if check.key == "abv")
    assert abv_check.status == "mismatch"
    assert abv_check.guidance_title == "TTB: Alcohol content statement requirements"
    assert abv_check.guidance_url.endswith("/ds-alcohol-content")


def test_proof_uses_a_dedicated_extraction_not_the_abv_text():
    extraction = mock_extraction()
    extraction.alcohol_content = ExtractedField(
        value="40% Alc./Vol.", evidence="40% Alc./Vol.", confidence=0.99
    )
    extraction.proof = ExtractedField(
        value="80 Proof", evidence="80 Proof", confidence=0.99
    )
    result = build_review(
        sample_application(abv=40, proof=80),
        extraction,
        provider_name="Mock provider",
    )
    proof = next(check for check in result.checks if check.key == "proof")
    assert proof.status == "match"
    assert proof.observed == "80 Proof"


def test_unread_proof_is_review_instead_of_using_abv_as_proof():
    extraction = mock_extraction()
    extraction.alcohol_content = ExtractedField(
        value="40% Alc./Vol.", evidence="40% Alc./Vol.", confidence=0.99
    )
    extraction.proof = ExtractedField(value=None, evidence=None, confidence=0.99)
    result = build_review(
        sample_application(abv=40, proof=80),
        extraction,
        provider_name="Mock provider",
    )
    proof = next(check for check in result.checks if check.key == "proof")
    assert proof.status == "review"
    assert proof.observed == "Not confidently read"


def test_country_origin_compares_the_visible_country_not_the_expected_search_text():
    extraction = mock_extraction()
    extraction.country_of_origin = ExtractedField(
        value="Mexico",
        evidence="PRODUCT OF MEXICO",
        expected_value_found=False,
        confidence=0.99,
    )
    result = build_review(
        sample_application(country_of_origin="United States"),
        extraction,
        provider_name="Mock provider",
    )
    country = next(check for check in result.checks if check.key == "country_of_origin")
    assert country.status == "mismatch"
    assert country.observed == "PRODUCT OF MEXICO"


def test_every_review_check_has_focused_ttb_guidance():
    result = build_review(
        sample_application(country_of_origin="Mexico"),
        mock_extraction(),
        provider_name="Mock provider",
    )
    assert all(check.guidance_title for check in result.checks)
    assert all(check.guidance_url and check.guidance_url.startswith("https://www.ttb.gov/") for check in result.checks)


def test_warning_ocr_variation_does_not_turn_a_matching_label_into_a_mismatch():
    extraction = mock_extraction()
    extraction.government_warning.verbatim_text = GOVERNMENT_WARNING.replace(
        "health problems", "serious health problems"
    )
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Mock provider",
    )
    warning = next(
        check for check in result.checks if check.key == "government_warning"
    )
    assert warning.status == "match"
    assert warning.expected == (
        "Government warning heading should be visible; typography requires human verification."
    )
    assert warning.observed == "Government warning heading detected."
    assert result.overall_status == "match"


def test_warning_boldness_does_not_affect_the_automated_screen():
    extraction = mock_extraction()
    extraction.government_warning.heading_bold = False
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Mock provider",
    )
    warning = next(
        check for check in result.checks if check.key == "government_warning"
    )
    assert warning.status == "match"
    assert "does not verify" in warning.explanation
    assert result.overall_status == "match"


def test_missing_warning_heading_routes_to_human_review():
    extraction = mock_extraction()
    extraction.government_warning.heading_text = None
    extraction.government_warning.verbatim_text = None
    extraction.government_warning.evidence = None
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Mock provider",
    )
    warning = next(
        check for check in result.checks if check.key == "government_warning"
    )
    assert warning.status == "review"
    assert warning.observed == "Government warning heading not confidently located."
    assert result.overall_status == "unable"


def test_low_confidence_routes_to_human_review():
    extraction = mock_extraction()
    extraction.brand_name.confidence = 0.4
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Mock provider",
    )
    assert result.overall_status == "unable"


def test_text_not_confidently_located_is_guidance_not_a_mismatch():
    extraction = mock_extraction()
    extraction.brand_name = ExtractedField(
        value=None,
        evidence=None,
        expected_value_found=False,
        confidence=0.95,
    )
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Mock provider",
    )
    brand = next(check for check in result.checks if check.key == "brand_name")
    assert brand.status == "review"
    assert brand.observed == "Not confidently located"
    assert "not proof" in brand.explanation
    assert result.overall_status == "unable"


def test_unreadable_required_field_does_not_pass():
    extraction = LabelExtraction()
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Test",
    )
    assert result.overall_status != "match"
