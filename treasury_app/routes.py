"""HTTP routes and request validation."""

from __future__ import annotations

import json
import time
from functools import lru_cache

from flask import Blueprint, current_app, jsonify, render_template, request
from pydantic import ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

from treasury_app.models import ApplicationData
from treasury_app.services.providers import (
    ImageInput,
    MiMoProvider,
    MockProvider,
    ProviderError,
)
from treasury_app.services.review import build_review

bp = Blueprint("main", __name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGES = 4


def has_valid_image_signature(content: bytes, mime_type: str) -> bool:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        ),
    }
    return signatures.get(mime_type, False)


@lru_cache(maxsize=4)
def _provider_for_config(
    provider_name: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
):
    if provider_name == "mock":
        return MockProvider()
    if provider_name != "mimo":
        raise ProviderError(f"Unsupported image provider: {provider_name}")
    return MiMoProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def get_provider():
    return _provider_for_config(
        current_app.config["AI_PROVIDER"],
        current_app.config["MIMO_API_KEY"],
        current_app.config["MIMO_BASE_URL"],
        current_app.config["MIMO_MODEL"],
        current_app.config["MIMO_TIMEOUT_SECONDS"],
    )


@bp.get("/")
def index():
    return render_template(
        "index.html",
        mock_mode=current_app.config["AI_PROVIDER"] == "mock",
    )


@bp.get("/health")
def health():
    configured = bool(current_app.config["MIMO_API_KEY"]) or (
        current_app.config["AI_PROVIDER"] == "mock"
    )
    return jsonify({"status": "ok", "provider_configured": configured})


@bp.post("/api/review")
def review_label():
    started = time.perf_counter()
    raw_application = request.form.get("application")
    if not raw_application:
        return _error("Application data is required.", 400)

    try:
        application = ApplicationData.model_validate(json.loads(raw_application))
    except json.JSONDecodeError:
        return _error("Application data must be valid JSON.", 400)
    except ValidationError as exc:
        return _error(
            "Please correct the application fields.",
            400,
            details=[
                {
                    "field": ".".join(str(part) for part in error["loc"]),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ],
        )

    uploads = [file for file in request.files.getlist("images") if file.filename]
    if not uploads:
        return _error("Add at least one label image.", 400)
    if len(uploads) > MAX_IMAGES:
        return _error(f"Upload no more than {MAX_IMAGES} images per label.", 400)

    images: list[ImageInput] = []
    for upload in uploads:
        if upload.mimetype not in ALLOWED_IMAGE_TYPES:
            return _error(
                f"{upload.filename} is not a supported JPEG, PNG, or WebP image.",
                415,
            )
        content = upload.read()
        if not content:
            return _error(f"{upload.filename} is empty.", 400)
        if not has_valid_image_signature(content, upload.mimetype):
            return _error(
                f"{upload.filename} does not contain a valid "
                f"{upload.mimetype.removeprefix('image/').upper()} image.",
                415,
            )
        images.append(
            ImageInput(
                content=content,
                mime_type=upload.mimetype,
                filename=upload.filename,
            )
        )

    try:
        provider = get_provider()
        extraction = provider.extract(images)
        result = build_review(
            application,
            extraction,
            provider_name=provider.name,
        )
        result.processing_ms = round((time.perf_counter() - started) * 1000)
        return jsonify(result.model_dump())
    except ProviderError as exc:
        return _error(str(exc), 503)


@bp.app_errorhandler(RequestEntityTooLarge)
def handle_too_large(_exc):
    maximum = current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return _error(f"The upload exceeds the {maximum} MB request limit.", 413)


def _error(message: str, status: int, details: list | None = None):
    payload: dict = {"error": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status
