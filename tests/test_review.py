from treasury_app.models import ApplicationData, LabelExtraction
from treasury_app.services.providers import MockProvider
from treasury_app.services.review import (
    GOVERNMENT_WARNING,
    build_review,
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
    return MockProvider().extract([])


def test_normalization_handles_case_and_punctuation():
    assert normalize_text("STONE'S THROW") == normalize_text("Stone’s Throw")


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
    assert all(check.status == "match" for check in result.checks)


def test_abv_difference_requires_attention():
    result = build_review(
        sample_application(abv=40),
        mock_extraction(),
        provider_name="Mock provider",
    )
    assert result.overall_status == "attention"
    assert "possible issues" in result.summary.lower()
    abv_check = next(check for check in result.checks if check.key == "abv")
    assert abv_check.status == "mismatch"


def test_warning_must_match_exact_wording():
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
    assert warning.status == "mismatch"
    assert result.overall_status == "attention"


def test_low_confidence_routes_to_human_review():
    extraction = mock_extraction()
    extraction.brand_name.confidence = 0.4
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Mock provider",
    )
    assert result.overall_status == "unable"


def test_unreadable_required_field_does_not_pass():
    extraction = LabelExtraction()
    result = build_review(
        sample_application(),
        extraction,
        provider_name="Test",
    )
    assert result.overall_status != "match"
