"""Application factory for the TTB Label Review Assistant."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv()

    app = Flask(__name__)
    app.config.from_mapping(
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024,
        AI_PROVIDER=os.getenv("AI_PROVIDER", "mimo").lower(),
        MIMO_API_KEY=os.getenv("MIMO_API_KEY", ""),
        MIMO_BASE_URL=os.getenv(
            "MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"
        ),
        MIMO_MODEL=os.getenv("MIMO_MODEL", "mimo-v2.5"),
        MIMO_TIMEOUT_SECONDS=float(os.getenv("MIMO_TIMEOUT_SECONDS", "25")),
    )

    if test_config:
        app.config.update(test_config)

    from treasury_app.routes import bp

    app.register_blueprint(bp)
    return app
