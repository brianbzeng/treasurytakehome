from types import SimpleNamespace

import pytest

from treasury_app.models import ApplicationData
from treasury_app.services.providers import (
    MiMoProvider,
    ProviderError,
    parse_extraction_response,
)


class FakeCompletions:
    def __init__(self, messages: list[str]):
        self.messages = messages
        self.calls = 0
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        message = self.messages[self.calls]
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=message))]
        )


def test_mimo_retries_once_after_an_invalid_structured_response():
    provider = MiMoProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
    )
    completions = FakeCompletions(["not json", "{}"])
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    application = ApplicationData(
        brand_name="Example Brand",
        class_type="Vodka",
        abv=40,
        net_contents="750 mL",
        producer_name_address="Example Distilling, Austin TX",
    )

    extraction = provider.extract([], application)

    assert extraction.brand_name.value is None
    assert completions.calls == 2
    assert completions.requests[0]["temperature"] == 0
    assert completions.requests[0]["max_completion_tokens"] == 2400
    assert completions.requests[0]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_extraction_parser_recovers_common_model_formatting_errors():
    extraction = parse_extraction_response(
        """```json
        {
          "brand_name": {
            "value": "Example Brand",
            "evidence": "EXAMPLE BRAND",
            "expected_value_found": "true",
            "confidence": "95%"
          },
          "alcohol_content": "14% vol.",
          "government_warning": {
            "heading_text": "GOVERNMENT WARNING:",
            "heading_bold": "unknown",
            "confidence": null
          },
          "notes": "Recovered model response"
        }
        ```"""
    )

    assert extraction.brand_name.expected_value_found is True
    assert extraction.brand_name.confidence == 0.95
    assert extraction.alcohol_content.value == "14% vol."
    assert extraction.government_warning.heading_bold is None
    assert extraction.government_warning.confidence == 0
    assert extraction.notes == ["Recovered model response"]


def test_extraction_parser_recovers_a_wrapped_object_with_surrounding_prose():
    extraction = parse_extraction_response(
        'Result follows: {"extraction":{"net_contents":{"value":"750 mL",'
        '"confidence":98}}} End.'
    )

    assert extraction.net_contents.value == "750 mL"
    assert extraction.net_contents.confidence == 0.98


def test_mimo_still_fails_safely_after_two_unrecoverable_responses():
    provider = MiMoProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
    )
    completions = FakeCompletions(["not json", "still not json"])
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    application = ApplicationData(
        brand_name="Example Brand",
        class_type="Vodka",
        abv=40,
        net_contents="750 mL",
        producer_name_address="Example Distilling, Austin TX",
    )

    with pytest.raises(ProviderError, match="invalid result"):
        provider.extract([], application)

    assert completions.calls == 2
