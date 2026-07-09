import io
import json


def application_payload():
    return {
        "application_id": "APP-001",
        "brand_name": "Old Tom Distillery",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "abv": 45,
        "proof": 90,
        "net_contents": "750 mL",
        "producer_name_address": "Old Tom Distillery, Louisville KY",
        "country_of_origin": None,
    }


JPEG_BYTES = b"\xff\xd8\xff\xe0mock-jpeg"
PNG_BYTES = b"\x89PNG\r\n\x1a\nmock-png"


def test_index_is_accessible(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"TTB Label Review Assistant" in response.data
    assert b"Mock mode is active" in response.data


def test_health_reports_provider(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "provider_configured": True}


def test_review_endpoint_returns_evidence_based_result(client):
    response = client.post(
        "/api/review",
        data={
            "application": json.dumps(application_payload()),
            "images": (io.BytesIO(JPEG_BYTES), "label.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.json["overall_status"] == "match"
    assert response.json["provider"] == "Mock provider"
    assert len(response.json["checks"]) >= 7


def test_review_rejects_unsupported_file_type(client):
    response = client.post(
        "/api/review",
        data={
            "application": json.dumps(application_payload()),
            "images": (io.BytesIO(b"not an image"), "label.txt", "text/plain"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 415


def test_review_rejects_spoofed_image_type(client):
    response = client.post(
        "/api/review",
        data={
            "application": json.dumps(application_payload()),
            "images": (io.BytesIO(b"not an image"), "label.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 415


def test_review_requires_image(client):
    response = client.post(
        "/api/review",
        data={"application": json.dumps(application_payload())},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_review_validates_application_fields(client):
    payload = application_payload()
    payload["brand_name"] = ""
    response = client.post(
        "/api/review",
        data={
            "application": json.dumps(payload),
            "images": (io.BytesIO(PNG_BYTES), "label.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.json["details"][0]["field"] == "brand_name"
