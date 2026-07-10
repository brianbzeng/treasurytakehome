# TTB Label Review Assistant

A lightweight proof of concept that helps Alcohol and Tobacco Tax and Trade
Bureau (TTB) reviewers compare label artwork with application data for
distilled spirits, wine, and malt beverages. The application uses Xiaomi MiMo for visual text extraction and
deterministic Python rules for every displayed match decision.

> This prototype is decision support only. It does not issue Certificates of
> Label Approval or replace review by an authorized TTB specialist.

## What the baseline supports

- Review one application with up to four label images.
- Review a CSV batch with progressive results and bounded concurrency.
- Extract label fields through the multimodal `mimo-v2.5` API.
- Select a distilled-spirit, wine, or malt-beverage review profile.
- Compare brand, class/type, ABV (when supplied), proof for distilled spirits,
  net contents, producer information, country of origin, and the government warning.
- Explain every result with expected values, observed values, and confidence.
- Route uncertain or unreadable evidence to a human instead of guessing.
- Present mismatches as possible issues for reviewer verification, never as a
  final compliance determination.
- Verify text fields by locating the application value in the label artwork
  instead of asking the model to independently classify competing marketing text.
- Link each possible issue to the focused TTB guidance page and summarize the
  relevant topic for the reviewer.
- Let a reviewer record a local, browser-only override and open COLAs Online;
  the prototype never approves or transmits an application.
- Run without OpenCV, PaddleOCR, Redis, or persistent file storage.

The original take-home prompt is preserved in
[`docs/ASSESSMENT.md`](docs/ASSESSMENT.md).

## Architecture

```text
Browser
  ├─ single form
  └─ batch coordinator (two concurrent items)
          ↓ multipart upload
Flask / Gunicorn
  ├─ input validation
  ├─ MiMo provider adapter
  ├─ Pydantic response validation
  └─ commodity-specific deterministic comparisons
          ↓
Evidence-based result (Matches / Needs attention / Unable to verify)
```

The model extracts observations only. It never chooses the final status. This
separation makes the compliance logic inspectable, testable, and replaceable.

## Local setup

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
| `MAX_UPLOAD_MB` | `12` | Total request upload limit |

MiMo receives images as Base64 data URLs. Uploaded images are not written to
the application filesystem or database.

## Batch CSV format

Download the template from the Batch review screen or create a UTF-8 CSV with:

```csv
id,beverage_type,brand_name,class_type,abv,proof,net_contents,producer_name_address,country_of_origin,image_filename
APP-001,distilled_spirits,Old Tom Distillery,Kentucky Straight Bourbon Whiskey,45,90,750 mL,"Old Tom Distillery, Louisville KY",,old-tom-front.jpg
```

`beverage_type` may be `distilled_spirits`, `wine`, or `malt_beverage`; omitted
values remain backward-compatible as `distilled_spirits`. `proof` and
`country_of_origin` may be blank. Wine and malt-beverage rows may leave `abv`
blank when the application does not supply it. Each row currently references one
image. The browser submits at most two rows concurrently and displays results
as they finish. Closing the browser stops an in-progress batch; a durable job
queue is intentionally deferred from this baseline.

## Testing

```bash
pytest
```

The tests cover normalization, fuzzy-name handling, ABV/proof arithmetic,
volume normalization, exact warning language, status aggregation, request
validation, and mock-provider API behavior.

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

## Safety and known limitations

- The prototype covers common label comparisons for distilled spirits, wine,
  and malt beverages; it is not a comprehensive commodity-specific rules engine.
- Model confidence is advisory and is never sufficient by itself to pass a
  check.
- A photograph cannot establish physical font size without trustworthy scale
  information.
- Boldness and legibility are visual model observations; uncertainty becomes
  manual review.
- Exact warning comparison is deliberately conservative. A transcription
  discrepancy creates a needs-attention result.
- External model use would require security, retention, data residency,
  accessibility, and authorization review before handling production federal
  data.
- Browser-coordinated batches are appropriate for the hosted assessment, not a
  production queue. A future iteration could add Render Key Value and a worker.
- The reviewer override is deliberately local to the browser and is not an
  approval, audit record, or submission to COLAs Online.

## Planned follow-up

1. Benchmark MiMo extraction against a curated label-image test set.
2. Add targeted second-pass transcription for uncertain warning statements.
3. Add optional OpenCV preprocessing and local OCR behind the same extraction
   interface when deployment capacity permits.
4. Add beverage-specific fields such as wine appellation/vintage and
   malt-beverage composition statements.
5. Add durable batch jobs, authentication, audit logs, and approved cloud
   storage for a production-oriented architecture.
