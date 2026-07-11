import csv
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence"
EXPECTED_BATCHES = {
    "beer/matched",
    "beer/mismatched",
    "wine/matched",
    "wine/mismatched",
    "distilled-spirits/matched",
    "distilled-spirits/mismatched",
    "distilled-spirits/distorted",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def test_evidence_manifests_cover_exactly_32_images():
    manifests = sorted(EVIDENCE_ROOT.glob("*/*/applications.csv"))
    batch_names = {
        manifest.parent.relative_to(EVIDENCE_ROOT).as_posix()
        for manifest in manifests
    }

    assert len(manifests) == 7
    assert batch_names == EXPECTED_BATCHES

    row_count = 0
    image_count = 0
    for manifest in manifests:
        rows = read_csv_rows(manifest)
        listed_images = [row["image_filename"] for row in rows]
        actual_images = sorted(
            path.name for path in (manifest.parent / "images").iterdir()
            if path.is_file()
        )

        assert len(listed_images) == len(set(listed_images))
        assert sorted(listed_images) == actual_images
        row_count += len(rows)
        image_count += len(actual_images)

    assert row_count == 32
    assert image_count == 32


def test_evidence_source_index_covers_every_application_row():
    manifest_keys = []
    for manifest in sorted(EVIDENCE_ROOT.glob("*/*/applications.csv")):
        commodity, batch = manifest.parent.relative_to(EVIDENCE_ROOT).parts
        commodity = commodity.replace("-", "_")
        manifest_keys.extend(
            (commodity, batch, row["image_filename"], row["id"])
            for row in read_csv_rows(manifest)
        )

    source_rows = read_csv_rows(EVIDENCE_ROOT / "source-index.csv")
    source_keys = [
        (
            row["commodity"],
            row["batch"],
            row["image_filename"],
            row["application_id"],
        )
        for row in source_rows
    ]

    assert len(manifest_keys) == len(set(manifest_keys)) == 32
    assert len(source_keys) == len(set(source_keys)) == 32
    assert set(source_keys) == set(manifest_keys)
    assert all(row["ttb_id"].isdigit() and len(row["ttb_id"]) == 14 for row in source_rows)
    assert all(row["source_url"].endswith(row["ttb_id"]) for row in source_rows)
    assert all(row["fixture_change"] for row in source_rows)


def test_evidence_contains_only_valid_images_and_no_archive_junk():
    files = [path for path in EVIDENCE_ROOT.rglob("*") if path.is_file()]
    forbidden_names = {".DS_Store", ".Rhistory"}
    forbidden_suffixes = {".zip", ".html", ".htm"}

    assert not [path for path in files if path.name in forbidden_names]
    assert not [path for path in files if path.suffix.lower() in forbidden_suffixes]

    images = [path for path in files if path.parent.name == "images"]
    assert len(images) == 32
    for image in images:
        signature = image.read_bytes()[:8]
        if image.suffix.lower() == ".png":
            assert signature == PNG_SIGNATURE
        elif image.suffix.lower() in {".jpg", ".jpeg"}:
            assert signature.startswith(JPEG_SIGNATURE)
        else:
            raise AssertionError(f"Unsupported evidence image type: {image}")
