# TTB Label Review Assistant

A lightweight proof of concept that helps Alcohol and Tobacco Tax and Trade
Bureau (TTB) reviewers screen label artwork for possible review items across
distilled spirits, wine, and malt beverages. The application uses Xiaomi MiMo
for visual text extraction and deterministic Python rules to present cautious,
evidence-based observations.

> This prototype is decision support only. It does not issue Certificates of
> Label Approval or replace review by an authorized TTB specialist.

**Live prototype:** <https://treasury.brianbzeng.com>

## Approach

- Compare one label and its submitted application values without requiring the
  reviewer to select a beverage type or Product Class/Type code.
- Run a quick diagnostic on one to 100 label images without requiring a CSV or
  typed application data.
- Compare as many as 300 CSV application rows with their referenced label
  images when expected-versus-observed screening is needed.
- Process image batches progressively with two concurrent requests and
  per-item retries.
- Extract label fields through the multimodal `mimo-v2.5` API.
- Identify the beverage profile and visible brand, class/type, alcohol statement,
  proof, net contents, producer/importer, country of origin, and government-warning heading.
- Explain possible review items with observed label evidence and confidence.
- Route uncertain or unreadable evidence to a human instead of guessing.
- In quick-scan mode, describe observations as possible review items rather
  than mismatches because no application record is supplied.
- In application-comparison mode, report differences between submitted values
  and visible label evidence without treating them as final determinations.
- Link each possible issue to the focused TTB guidance page and summarize the
  relevant topic for the reviewer.
- Provide a save/print view and a link to COLAs Online; the prototype never
  approves or transmits an application.
- Run without OpenCV, PaddleOCR, Redis, or persistent file storage.

The workflow intentionally separates three jobs that have different certainty:

1. **Review one label** compares submitted values to one label and up to four
   label views.
2. **Quick label scan** accepts images only and highlights possible visible
   review items; it never claims an application mismatch.
3. **Review a batch** uses a CSV manifest and matching images for the most
   structured, field-by-field comparison.

The original take-home prompt is preserved in
[`docs/ASSESSMENT.md`](docs/ASSESSMENT.md).

## Tools used

- **Python 3.11, Flask, Jinja, and vanilla JavaScript/CSS** for a small,
  server-rendered application with no front-end build step.
- **Xiaomi MiMo `mimo-v2.5`** as the remote multimodal image/OCR provider.
- **Pydantic** to validate model responses before review logic uses them.
- **Deterministic Python comparison and normalization rules** for ABV/proof,
  volume, text matching, and status aggregation.
- **pytest and GitHub Actions** for automated regression tests.
- **Gunicorn and Render** for hosted deployment.

## Architecture

```text
Browser
  ├─ Individual comparison (up to four views)
  │      └─ /api/review → expected-versus-observed discrepancies
  ├─ Quick label scan (one to 100 images)
  │      └─ /api/screen → possible label review items
  └─ CSV batch comparison (up to 300 rows)
         └─ /api/review → expected-versus-observed discrepancies
                    ↓ multipart uploads
Flask / Gunicorn
  ├─ input validation
  ├─ MiMo provider adapter
  ├─ Pydantic response validation
  └─ commodity-aware deterministic review rules
          ↓
Evidence-based result (No review item / Possible review item / Difference / Unable to verify)
```

The model extracts observations only. Deterministic rules convert them into
cautious review leads; neither layer makes a final compliance determination.

## Setup and run

Prerequisites:

- Python 3.11+
- A Xiaomi MiMo API key

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `MIMO_API_KEY` in `.env`, then run:

```bash
flask --app app run --debug
```

Open <http://127.0.0.1:5000>.

The landing page links to three focused workflows:

- `/review` for one submitted application and its label views
- `/quick-scan` for image-only label diagnostics
- `/batch-review` for CSV-backed application comparison

### Mock development mode

To exercise the complete interface without making API calls:

```bash
AI_PROVIDER=mock flask --app app run --debug
```

Mock mode returns fixed example label observations and is visibly identified in
the interface. It is disabled unless explicitly configured.

## MiMo configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MIMO_API_KEY` | none | Required unless mock mode is enabled |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | API endpoint |
| `MIMO_MODEL` | `mimo-v2.5` | Vision-capable model |
| `MIMO_TIMEOUT_SECONDS` | `25` | Upstream request timeout |
| `AI_PROVIDER` | `mimo` | Set to `mock` only for local demonstration |
| `MAX_UPLOAD_MB` | `12` | Per-label-image request upload limit |

MiMo receives images as Base64 data URLs. Uploaded images are not written to
the application filesystem or database.

## Quick label scan

Choose one to 100 JPEG, PNG, or WebP images. Each uploaded file is screened as
one label. This is a fast diagnostic for major visible review items and
uncertainty; it cannot identify an application mismatch because no application
record is supplied. The browser sends at most two requests at once, shows
results as they finish, and lets the reviewer retry only a label that the image
service could not process.

## Review one label

Choose **Review one label** when the reviewer has the submitted values for a
single application. Enter the brand name, class/type designation, optional ABV
and proof, total bottle capacity, applicant name and address, and country of
origin when applicable. Then add up to four front, back, or side label views.

The reviewer does not choose a beverage type. MiMo infers only a broad profile
from the visible label - distilled spirits, wine, malt beverage, or unknown -
to choose appropriate comparison behavior and TTB guidance. It does not choose
or validate a specific TTB Product Class/Type code. ABV is optional on the
form, but an inferred distilled-spirit label without a submitted ABV is routed
to human review because there is no value to compare.

## Review a batch

Choose **Review a batch**, download the CSV template, and fill one row per
application. Then upload the CSV and every referenced label image. The
comparison mode supports up to 300 rows and reports differences between the
supplied values and visible label evidence.

Required CSV columns:

```text
id,brand_name,class_type,abv,proof,net_contents,producer_name_address,country_of_origin,image_filename
```

`image_filename` must exactly match the name of an uploaded JPEG, PNG, or WebP
file. ABV and proof are optional when those values were not supplied with the
application. The assistant infers the broad beverage profile from each label;
the CSV does not require a beverage-type or Product Class/Type column. Existing
manifests with an optional `beverage_type` column remain compatible. The browser
runs two comparisons at a time and provides a retry control for an individual
processing failure.

Uploaded images and application values are held only for the active browser
session and request; the app does not persist them to its filesystem or a
database.

## Testing

```bash
pytest
```

The tests cover both API workflows, normalization, fuzzy-name handling,
ABV/proof arithmetic, volume normalization, warning-heading handling, status
aggregation, request validation, and mock-provider behavior.

GitHub Actions runs this suite for every pull request.

## Render deployment

1. Create a Render Web Service connected to this repository.
2. Select Python and a paid instance to avoid free-tier spin-down.
3. Add `MIMO_API_KEY` as a secret environment variable.
4. Render will use [`render.yaml`](render.yaml), or configure manually:

   - Build command: `pip install -r requirements.txt`
   - Start command:
     `gunicorn "app:create_app()" --worker-class gthread --workers 1 --threads 4 --timeout 60`

No persistent disk is required. A 512 MB paid Starter instance should be
sufficient for the baseline because model inference runs remotely; confirm with
Render metrics under realistic uploads.

## Assumptions and deliberate limitations

- The prototype covers common label comparisons for distilled spirits, wine,
  and malt beverages; it is not a comprehensive commodity-specific rules engine.
- Model confidence is advisory and is never sufficient by itself to pass a
  check.
- A photograph cannot establish physical font size without trustworthy scale
  information.
- Boldness and legibility are visual model observations; uncertainty becomes
  manual review.
- The automated screen checks whether the government-warning heading can be
  confidently located. Exact wording, typography, legibility, and placement
  remain human-review items.
- External model use would require security, retention, data residency,
  accessibility, and authorization review before handling production federal
  data.
- Browser-coordinated batches are appropriate for the hosted assessment, not a
  production queue. A future iteration could add Render Key Value and a worker.
- Results and retries are browser-local and are not an approval, durable audit
  record, or submission to COLAs Online.

## Pull request delivery log

Every implementation change was delivered through a pull request:

| PR | Summary |
| --- | --- |
| [#1](https://github.com/brianbzeng/treasurytakehome/pull/1) | Established the Flask/MiMo label-review baseline. |
| [#2](https://github.com/brianbzeng/treasurytakehome/pull/2) | Added possible-issue guidance to review results. |
| [#3](https://github.com/brianbzeng/treasurytakehome/pull/3) | Made expected text verification evidence-based rather than a loose OCR match. |
| [#4](https://github.com/brianbzeng/treasurytakehome/pull/4) | Added reviewer continuation controls and focused TTB guidance links. |
| [#5](https://github.com/brianbzeng/treasurytakehome/pull/5) | Improved government-warning output and batch-result layout. |
| [#6](https://github.com/brianbzeng/treasurytakehome/pull/6) | Separated ABV and proof extraction and comparison. |
| [#7](https://github.com/brianbzeng/treasurytakehome/pull/7) | Relaxed government-warning screening to avoid unreliable typography claims. |
| [#8](https://github.com/brianbzeng/treasurytakehome/pull/8) | Refined matching language and producer-evidence handling. |
| [#9](https://github.com/brianbzeng/treasurytakehome/pull/9) | Recognized legal-suffix variants in brand-name evidence. |
| [#10](https://github.com/brianbzeng/treasurytakehome/pull/10) | Recovered malformed batch results and added country-of-origin comparison. |
| [#11](https://github.com/brianbzeng/treasurytakehome/pull/11) | Added wine and malt-beverage review profiles. |
| [#12](https://github.com/brianbzeng/treasurytakehome/pull/12) | Constrained capacity entry and aligned form labels with COLA terminology. |
| [#13](https://github.com/brianbzeng/treasurytakehome/pull/13) | Simplified batch results and normalized common European label conventions. |
| [#14](https://github.com/brianbzeng/treasurytakehome/pull/14) | Added per-item retry for failed batch reviews. |
| [#15](https://github.com/brianbzeng/treasurytakehome/pull/15) | Improved MiMo failure recovery and added reviewer-friendly save/print output. |
| [#16](https://github.com/brianbzeng/treasurytakehome/pull/16) | Added an image-only label-screening path. |
| [#17](https://github.com/brianbzeng/treasurytakehome/pull/17) | Combined individual review, quick scan, and CSV batch comparison. |
| [#18](https://github.com/brianbzeng/treasurytakehome/pull/18) | Restored individual review without requiring a beverage-type dropdown. |
| [#19](https://github.com/brianbzeng/treasurytakehome/pull/19) | Separated the three workflows into dedicated, more compact pages. |

## Planned follow-up

1. Benchmark MiMo extraction against a curated label-image test set.
2. Add targeted second-pass transcription for uncertain warning statements.
3. Add optional OpenCV preprocessing and local OCR behind the same extraction
   interface when deployment capacity permits.
4. Add beverage-specific fields such as wine appellation/vintage and
   malt-beverage composition statements.
5. Add durable batch jobs, authentication, audit logs, and approved cloud
   storage for a production-oriented architecture.
