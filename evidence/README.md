# Reproducible label-review evidence

This directory contains the representative label images and CSV application
manifests used during manual testing of the prototype. It is intentionally a
small, GitHub-friendly subset of the working corpus: six complete five-item
batches cover matched and deliberately mismatched beer, wine, and distilled
spirits, and one two-item batch exercises distorted artwork.

These fixtures demonstrate the test inputs; they are not a claim of regulatory
approval or a statistically representative accuracy benchmark. Vision-model
output can vary, and any `Human review required` result should be treated as a
safe uncertainty outcome rather than a false result.

## Directory layout

```text
evidence/
├── source-index.csv
├── beer/
│   ├── matched/{applications.csv, images/}
│   └── mismatched/{applications.csv, images/}
├── wine/
│   ├── matched/{applications.csv, images/}
│   └── mismatched/{applications.csv, images/}
└── distilled-spirits/
    ├── matched/{applications.csv, images/}
    ├── mismatched/{applications.csv, images/}
    └── distorted/
        ├── applications.csv
        └── images/
```

Every `applications.csv` value in `image_filename` has an exact filename match
in its sibling `images/` directory. `source-index.csv` maps each fixture to the
public TTB ID and direct registry URL from which its artwork was obtained and
records intentional test changes.

## Expected outcomes

| Batch | Items | Intended result |
| --- | ---: | --- |
| `beer/matched` | 5 | No discrepancy between the supplied values and visible label evidence. |
| `beer/mismatched` | 5 | The deliberately changed submitted ABV should be reported. |
| `wine/matched` | 5 | No discrepancy, including European decimal/capacity notation and `Italia`/Italy normalization where present. |
| `wine/mismatched` | 5 | The deliberately changed submitted ABV should be reported. |
| `distilled-spirits/matched` | 5 | No discrepancy between the supplied values and visible label evidence. |
| `distilled-spirits/mismatched` | 5 | One deliberate numeric discrepancy per row: proof for 1 and 17, ABV for 5 and 12, and capacity for 9. |
| `distilled-spirits/distorted` | 2 | If readable, report the capacity discrepancy for 5 and origin discrepancy for 17; otherwise route the item to human review. |

The two distorted images were made from the corresponding files in
`distilled-spirits/matched/images/`. File 5 simulates low light, glare, and
slight perspective skew. File 17 simulates rotation, glare, and modest blur.
The clean originals are already represented by the matched batch's `5.png` and
`17.jpg` and are not duplicated in the distorted directory.

## Run a batch

1. Start the application using the setup instructions in the root README.
2. Open **Review a batch**.
3. Upload one batch's `applications.csv`.
4. Select all files in that same batch's `images/` directory.
5. Start the comparison and review the per-label results and batch summary.

Run each directory as a separate batch. Do not combine manifests or upload
files from another batch; the image filenames are reused across some batches
by design.

## Provenance and fixture construction

The label artwork was downloaded from the public TTB COLA Registry while the
prototype was being developed. The source TTB IDs are retained in
`source-index.csv`; a registry record can be located by searching that ID in
the COLA Public Registry. The direct registry URL pattern used during collection
was
`https://www.ttbonline.gov/colasonline/viewColaDetails.do?action=publicDisplaySearchBasic&ttbid=<TTB_ID>`.
CSV manifests are manually assembled test fixtures, not official exports from
COLAs.

Matched manifests contain the values used as the expected baseline. Mismatched
manifests keep the source artwork unchanged and deliberately alter a submitted
numeric value, providing a known expected finding without requiring subjective
brand or class/type interpretation. Only the two files in
`distilled-spirits/distorted/images/` alter image quality.

## Data and rights note

The selected evidence contains no credentials, API keys, saved sessions, or
private account data. It does contain publicly displayed product artwork,
trademarks, barcodes, business names, and business addresses. Those materials
remain the property of their respective owners and are included only to
document and reproduce this assessment's testing. The much larger local archive
of saved registry HTML, scripts, styles, and duplicated resources is excluded
because it is unnecessary for reproduction and may contain additional contact
fields.

The package contains 41 files and is approximately 13.4 MiB. Its largest file
is approximately 2.5 MiB, well below GitHub's 100 MiB per-file limit.
