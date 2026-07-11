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


def test_index_links_to_each_dedicated_review_workflow(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"TTB Label Review Assistant" in response.data
    assert b"Mock mode is active" in response.data
    assert b"AI-assisted guidance only" in response.data
    assert b"Review one label" in response.data
    assert b"Quick label scan" in response.data
    assert b"Review a batch" in response.data
    assert b"Open one-label review" in response.data
    assert b"Submitted application values" not in response.data
    assert b'id="compare-form"' not in response.data
    assert b'individual-beverage-type' not in response.data


def test_browser_assets_use_one_content_fingerprint(client):
    response = client.get("/")
    html = response.get_data(as_text=True)
    versions = {
        url.split("?v=", 1)[1].split('"', 1)[0]
        for url in html.split('"')
        if url.startswith("/static/") and "?v=" in url
    }
    assert len(versions) == 1
    assert html.count("?v=") == 3


def test_individual_review_renders_only_the_individual_form(client):
    response = client.get("/review")
    assert response.status_code == 200
    assert b'id="individual-form"' in response.data
    assert b"Submitted application values" in response.data
    assert b'id="screen-form"' not in response.data
    assert b'id="compare-form"' not in response.data


def test_quick_scan_renders_only_the_quick_scan_form(client):
    response = client.get("/quick-scan")
    assert response.status_code == 200
    assert b'id="screen-form"' in response.data
    assert b"Choose one to 100 label images" in response.data
    assert b'id="individual-form"' not in response.data
    assert b'id="compare-form"' not in response.data


def test_batch_review_renders_only_the_csv_comparison_form(client):
    response = client.get("/batch-review")
    assert response.status_code == 200
    assert b'id="compare-form"' in response.data
    assert b"CSV manifest" in response.data
    assert b"Download CSV template" in response.data
    assert b'id="individual-form"' not in response.data
    assert b'id="screen-form"' not in response.data


def test_health_reports_provider(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "provider_configured": True}


def test_label_only_screen_returns_possible_review_result(client):
    response = client.post(
        "/api/screen",
        data={
            "label_id": "example-label.jpg",
            "image": (io.BytesIO(JPEG_BYTES), "label.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.json["label_id"] == "example-label.jpg"
    assert response.json["overall_status"] == "match"
    assert response.json["beverage_type"] == "distilled_spirits"
    assert "No possible" not in response.json["summary"]
    assert "did not identify a major visible review item" in response.json["summary"]
    assert all(check["status"] != "mismatch" for check in response.json["checks"])


def test_label_only_screen_requires_one_supported_image(client):
    missing = client.post("/api/screen", data={}, content_type="multipart/form-data")
    assert missing.status_code == 400

    unsupported = client.post(
        "/api/screen",
        data={"image": (io.BytesIO(b"not an image"), "label.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert unsupported.status_code == 415

    multiple = client.post(
        "/api/screen",
        data={
            "image": [
                (io.BytesIO(JPEG_BYTES), "one.jpg", "image/jpeg"),
                (io.BytesIO(JPEG_BYTES), "two.jpg", "image/jpeg"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert multiple.status_code == 400


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
    assert all(check["guidance_url"].startswith("https://www.ttb.gov/") for check in response.json["checks"])


def test_review_endpoint_supports_wine_without_an_abv_statement(client):
    payload = application_payload()
    payload.update({"beverage_type": "wine", "class_type": "Red Wine"})
    del payload["abv"]
    del payload["proof"]
    response = client.post(
        "/api/review",
        data={
            "application": json.dumps(payload),
            "images": (io.BytesIO(JPEG_BYTES), "label.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "abv" not in {check["key"] for check in response.json["checks"]}


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
