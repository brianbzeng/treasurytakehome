from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from treasury_app.models import ApplicationData
from treasury_app.services import providers as providers_module
from treasury_app.services.providers import (
    MAX_COMPLETION_TOKENS,
    MAX_PROVIDER_IMAGE_EDGE,
    SCREEN_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    ImageInput,
    MiMoProvider,
    ProviderError,
    optimize_image_for_provider,
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


def test_mimo_uses_compact_request_configuration_without_hidden_retries():
    provider = MiMoProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
    )
    assert provider.client.max_retries == 0
    completions = FakeCompletions(["{}"])
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
    assert completions.calls == 1
    assert completions.requests[0]["temperature"] == 0
    assert (
        completions.requests[0]["max_completion_tokens"]
        == MAX_COMPLETION_TOKENS
    )
    assert completions.requests[0]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert completions.requests[0]["messages"][0]["content"] == SYSTEM_PROMPT
    prompt = completions.requests[0]["messages"][1]["content"][-1]["text"]
    assert "Beverage profile: Determine from the visible label" in prompt


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


def test_extraction_parser_accepts_the_compact_response_schema():
    extraction = parse_extraction_response(
        '{"t":"malt_beverage","b":{"v":"Example Beer","f":true,"c":0.97},'
        '"y":{"v":"IPA","c":0.93},"a":{"v":"6.2% Alc./Vol.","c":0.99},'
        '"n":{"v":"12 FL OZ","c":0.98},"w":{"h":"GOVERNMENT WARNING:","c":0.95}}'
    )

    assert extraction.beverage_type == "malt_beverage"
    assert extraction.brand_name.value == "Example Beer"
    assert extraction.brand_name.evidence == "Example Beer"
    assert extraction.brand_name.expected_value_found is True
    assert extraction.class_type.value == "IPA"
    assert extraction.alcohol_content.value == "6.2% Alc./Vol."
    assert extraction.net_contents.value == "12 FL OZ"
    assert extraction.government_warning.heading_text == "GOVERNMENT WARNING:"


def test_extraction_parser_accepts_a_warning_only_compact_response():
    extraction = parse_extraction_response(
        '{"t":null,"w":{"h":"GOVERNMENT WARNING:","c":0.9}}'
    )

    assert extraction.brand_name.value is None
    assert extraction.government_warning.heading_text == "GOVERNMENT WARNING:"


def test_mimo_fails_safely_without_an_invisible_provider_retry():
    provider = MiMoProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
    )
    completions = FakeCompletions(["not json"])
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

    assert completions.calls == 1


def test_mimo_supports_label_only_screening():
    provider = MiMoProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
    )
    completions = FakeCompletions(
        ['{"beverage_type":"wine","brand_name":{"value":"Example Wine","confidence":0.9}}']
    )
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    extraction = provider.screen([])

    assert extraction.beverage_type == "wine"
    assert extraction.brand_name.value == "Example Wine"
    request = completions.requests[0]
    assert request["messages"][0]["content"] == SCREEN_SYSTEM_PROMPT
    assert len(SCREEN_SYSTEM_PROMPT) < len(SYSTEM_PROMPT) / 2


def test_provider_image_optimization_reduces_large_transport_payload():
    source = Image.effect_noise((1200, 800), 80).convert("RGB")
    upload = BytesIO()
    source.save(upload, format="PNG")
    original = ImageInput(
        content=upload.getvalue(),
        mime_type="image/png",
        filename="large-label.png",
    )

    optimized = optimize_image_for_provider(original)

    assert optimized.mime_type == "image/jpeg"
    assert len(optimized.content) < len(original.content) * 0.9
    with Image.open(BytesIO(optimized.content)) as result:
        assert max(result.size) == MAX_PROVIDER_IMAGE_EDGE


def test_provider_image_optimization_falls_back_for_invalid_data():
    original = ImageInput(
        content=b"not-an-image",
        mime_type="image/jpeg",
        filename="broken.jpg",
    )

    assert optimize_image_for_provider(original) is original


def test_provider_image_optimization_rejects_excessive_dimensions(monkeypatch):
    source = Image.new("RGB", (20, 20), "white")
    upload = BytesIO()
    source.save(upload, format="PNG")
    original = ImageInput(
        content=upload.getvalue(),
        mime_type="image/png",
        filename="oversized-label.png",
    )
    monkeypatch.setattr(providers_module, "MAX_PROVIDER_IMAGE_PIXELS", 100)

    with pytest.raises(ProviderError, match="16 megapixels"):
        optimize_image_for_provider(original)
