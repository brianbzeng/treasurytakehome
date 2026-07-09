import pytest

from treasury_app import create_app


@pytest.fixture()
def app():
    return create_app(
        {
            "TESTING": True,
            "AI_PROVIDER": "mock",
            "MIMO_API_KEY": "",
            "MAX_CONTENT_LENGTH": 12 * 1024 * 1024,
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()
