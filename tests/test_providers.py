from types import SimpleNamespace

from treasury_app.models import ApplicationData
from treasury_app.services.providers import MiMoProvider


class FakeCompletions:
    def __init__(self, messages: list[str]):
        self.messages = messages
        self.calls = 0

    def create(self, **_kwargs):
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
