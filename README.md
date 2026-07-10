# TTB Label Review Assistant

A lightweight proof of concept that helps Alcohol and Tobacco Tax and Trade
Bureau (TTB) reviewers screen label artwork for possible review items across
distilled spirits, wine, and malt beverages. The application uses Xiaomi MiMo
for visual text extraction and deterministic Python rules to present cautious,
evidence-based observations.

> This prototype is decision support only. It does not issue Certificates of
> Label Approval or replace review by an authorized TTB specialist.

## What the baseline supports

- Screen one to 100 label images without requiring a CSV or typed application data.
- Process label images progressively with two concurrent requests and per-label retries.
- Extract label fields through the multimodal `mimo-v2.5` API.
- Identify the beverage profile and visible brand, class/type, alcohol statement,
  proof, net contents, producer/importer, country of origin, and government-warning heading.
- Explain possible review items with observed label evidence and confidence.
- Route uncertain or unreadable evidence to a human instead of guessing.
- Never call a result a mismatch or a final compliance determination because no
  application record is submitted with the label image.
- Link each possible issue to the focused TTB guidance page and summarize the
  relevant topic for the reviewer.
- Provide a save/print view and a link to COLAs Online; the prototype never
  approves or transmits an application.
- Run without OpenCV, PaddleOCR, Redis, or persistent file storage.

The original take-home prompt is preserved in
[`docs/ASSESSMENT.md`](docs/ASSESSMENT.md).

## Architecture

```text
Browser
  └─ label-only batch coordinator (two concurrent items)
          ↓ multipart upload
Flask / Gunicorn
  ├─ input validation
  ├─ MiMo provider adapter
  ├─ Pydantic response validation
  └─ commodity-aware label-only screening
          ↓
Evidence-based result (No possible review items / Possible review items / Unable to verify)
```

The model extracts observations only. Deterministic rules convert them into
cautious review leads; neither layer makes a final compliance determination.

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
| `MAX_UPLOAD_MB` | `12` | Per-label-image request upload limit |

MiMo receives images as Base64 data URLs. Uploaded images are not written to
the application filesystem or database.

## Label-only screening

Choose one to 100 JPEG, PNG, or WebP images. Each uploaded file is screened as
one label. The browser sends at most two requests at once, shows results as they
finish, and lets the reviewer retry only a label that the image service could
not process. The app does not persist uploaded images or application data.

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
