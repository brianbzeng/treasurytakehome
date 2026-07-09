const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

const singleTab = qs("#single-tab");
const batchTab = qs("#batch-tab");
const singlePanel = qs("#single-panel");
const batchPanel = qs("#batch-panel");
const reviewForm = qs("#review-form");
const resultRegion = qs("#single-result");
const formError = qs("#form-error");
const reviewButton = qs("#review-button");
const imageInput = qs("#label-images");
const selectedFiles = qs("#selected-files");

let batchResults = [];

function selectMode(mode) {
  const isSingle = mode === "single";
  singleTab.classList.toggle("active", isSingle);
  batchTab.classList.toggle("active", !isSingle);
  singleTab.setAttribute("aria-selected", String(isSingle));
  batchTab.setAttribute("aria-selected", String(!isSingle));
  singlePanel.classList.toggle("hidden", !isSingle);
  batchPanel.classList.toggle("hidden", isSingle);
  (isSingle ? singleTab : batchTab).focus();
}

singleTab.addEventListener("click", () => selectMode("single"));
batchTab.addEventListener("click", () => selectMode("batch"));
qsa(".mode-button").forEach((button) => {
  button.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      selectMode(button === singleTab ? "batch" : "single");
    }
  });
});

imageInput.addEventListener("change", () => {
  selectedFiles.replaceChildren(
    ...[...imageInput.files].map((file) => {
      const item = document.createElement("li");
      item.textContent = `${file.name} (${formatBytes(file.size)})`;
      return item;
    }),
  );
});

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function applicationFromForm(form) {
  const data = new FormData(form);
  return {
    application_id: data.get("application_id") || null,
    brand_name: data.get("brand_name"),
    class_type: data.get("class_type"),
    abv: Number(data.get("abv")),
    proof: data.get("proof") ? Number(data.get("proof")) : null,
    net_contents: data.get("net_contents"),
    producer_name_address: data.get("producer_name_address"),
    country_of_origin: data.get("country_of_origin") || null,
  };
}

async function submitReview(application, images) {
  const payload = new FormData();
  payload.append("application", JSON.stringify(application));
  images.forEach((image) => payload.append("images", image));
  const response = await fetch("/api/review", { method: "POST", body: payload });
  const body = await response.json().catch(() => ({
    error: "The server returned an unreadable response.",
  }));
  if (!response.ok) throw new Error(body.error || "The review could not be completed.");
  return body;
}

reviewForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError(formError);
  resultRegion.classList.add("hidden");

  if (imageInput.files.length > 4) {
    return showError(formError, "Choose no more than four label images.");
  }

  reviewButton.disabled = true;
  reviewButton.textContent = "Reviewing label…";
  try {
    const result = await submitReview(
      applicationFromForm(reviewForm),
      [...imageInput.files],
    );
    renderResult(result);
  } catch (error) {
    showError(formError, error.message);
  } finally {
    reviewButton.disabled = false;
    reviewButton.textContent = "Review this label";
  }
});

function renderResult(result) {
  const statusCopy = {
    match: ["Matches application", "All checks matched"],
    attention: ["Needs attention", "A difference was found"],
    unable: ["Human review required", "Some evidence is uncertain"],
  };
  const [heading, shortStatus] = statusCopy[result.overall_status];

  const header = element("div", `result-header ${result.overall_status}`);
  const title = element("h2", "", heading);
  title.id = "result-heading";
  header.append(
    title,
    element("p", "", result.summary),
    element(
      "p",
      "result-meta",
      `${shortStatus} · ${result.processing_ms} ms · ${result.provider}`,
    ),
  );

  const disclaimer = element(
    "p",
    "advisory result-disclaimer",
    "Possible issues are AI-assisted guidance only. They may be incorrect or incomplete; verify the label artwork and applicable requirements before acting.",
  );

  const list = element("div", "check-list");
  result.checks.forEach((check) => list.append(renderCheck(check)));
  resultRegion.replaceChildren(header, disclaimer, list);
  resultRegion.classList.remove("hidden");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  resultRegion.scrollIntoView({
    behavior: reduceMotion ? "auto" : "smooth",
    block: "start",
  });
}

function renderCheck(check) {
  const statusNames = {
    match: "Matches",
    review: "Review",
    mismatch: "Difference",
  };
  const card = element("article", `check-card ${check.status}`);
  const heading = element("h3", "", check.label);
  const status = element("p", "status-label", statusNames[check.status]);
  const description = element("p", "", check.explanation);
  const details = document.createElement("dl");
  addDetail(details, "Expected", check.expected || "Not supplied");
  addDetail(details, "Observed", check.observed || "Not confidently detected");
  if (check.confidence !== null && check.confidence !== undefined) {
    addDetail(details, "Confidence", `${Math.round(check.confidence * 100)}%`);
  }
  card.append(heading, status, description, details);
  return card;
}

function addDetail(list, name, value) {
  list.append(element("dt", "", name), element("dd", "", value));
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function showError(container, message) {
  container.textContent = message;
  container.classList.remove("hidden");
  container.focus();
}

function hideError(container) {
  container.textContent = "";
  container.classList.add("hidden");
}

const templateHeaders = [
  "id", "brand_name", "class_type", "abv", "proof", "net_contents",
  "producer_name_address", "country_of_origin", "image_filename",
];
const templateRow = [
  "APP-001", "Old Tom Distillery", "Kentucky Straight Bourbon Whiskey",
  "45", "90", "750 mL", "Old Tom Distillery, Louisville KY", "",
  "old-tom-front.jpg",
];

qs("#template-link").addEventListener("click", (event) => {
  event.preventDefault();
  downloadText(
    "ttb-batch-template.csv",
    `${templateHeaders.map(csvEscape).join(",")}\n${templateRow.map(csvEscape).join(",")}\n`,
  );
});

qs("#batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = qs("#batch-error");
  hideError(error);
  batchResults = [];
  qs("#batch-result-body").replaceChildren();

  try {
    const csvFile = qs("#batch-csv").files[0];
    const imageFiles = [...qs("#batch-images").files];
    const rows = parseCsv(await csvFile.text());
    validateBatchRows(rows);
    const imagesByName = new Map(imageFiles.map((file) => [file.name, file]));
    for (const row of rows) {
      if (!imagesByName.has(row.image_filename)) {
        throw new Error(`Image not found for ${row.id}: ${row.image_filename}`);
      }
    }
    await processBatch(rows, imagesByName);
  } catch (problem) {
    showError(error, problem.message);
  }
});

function parseCsv(text) {
  const matrix = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field.trim());
      field = "";
    } else if (char === "\n") {
      row.push(field.trim());
      if (row.some(Boolean)) matrix.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }
  row.push(field.trim());
  if (row.some(Boolean)) matrix.push(row);
  if (quoted) throw new Error("The CSV contains an unclosed quoted field.");
  if (matrix.length < 2) throw new Error("The CSV must include a header and at least one row.");

  const headers = matrix[0];
  return matrix.slice(1).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])),
  );
}

function validateBatchRows(rows) {
  if (rows.length > 300) throw new Error("A batch may contain no more than 300 applications.");
  rows.forEach((row, index) => {
    for (const header of templateHeaders) {
      if (!(header in row)) throw new Error(`Missing required CSV column: ${header}`);
    }
    for (const field of ["id", "brand_name", "class_type", "abv", "net_contents", "producer_name_address", "image_filename"]) {
      if (!row[field]) throw new Error(`Row ${index + 2} is missing ${field}.`);
    }
    if (!Number(row.abv)) throw new Error(`Row ${index + 2} has an invalid ABV.`);
  });
}

async function processBatch(rows, imagesByName) {
  const progress = qs("#batch-progress");
  const results = qs("#batch-results");
  const button = qs("#batch-button");
  const bar = qs("#progress-bar");
  let nextIndex = 0;
  let completed = 0;

  progress.classList.remove("hidden");
  results.classList.remove("hidden");
  button.disabled = true;
  button.textContent = "Batch in progress…";
  bar.max = rows.length;
  bar.value = 0;
  updateProgress(completed, rows.length);

  async function worker() {
    while (nextIndex < rows.length) {
      const row = rows[nextIndex];
      nextIndex += 1;
      const application = {
        application_id: row.id,
        brand_name: row.brand_name,
        class_type: row.class_type,
        abv: Number(row.abv),
        proof: row.proof ? Number(row.proof) : null,
        net_contents: row.net_contents,
        producer_name_address: row.producer_name_address,
        country_of_origin: row.country_of_origin || null,
      };
      try {
        const result = await submitReview(application, [imagesByName.get(row.image_filename)]);
        batchResults.push(result);
        appendBatchRow(result);
      } catch (error) {
        const failure = {
          application_id: row.id,
          overall_status: "unable",
          summary: error.message,
          processing_ms: null,
          checks: [],
        };
        batchResults.push(failure);
        appendBatchRow(failure);
      }
      completed += 1;
      bar.value = completed;
      updateProgress(completed, rows.length);
    }
  }

  try {
    await Promise.all([worker(), worker()]);
  } finally {
    button.disabled = false;
    button.textContent = "Start batch review";
  }
}

function updateProgress(completed, total) {
  qs("#progress-text").textContent =
    completed === total
      ? `${total} of ${total} applications complete.`
      : `${completed} of ${total} applications complete. You may review finished items below.`;
}

function appendBatchRow(result) {
  const row = document.createElement("tr");
  const statusNames = {
    match: "Matches",
    attention: "Needs attention",
    unable: "Human review required",
  };
  row.append(
    element("td", "", result.application_id || "Not supplied"),
    element("td", "", statusNames[result.overall_status]),
    renderPossibleIssues(result),
    element("td", "", result.summary),
    element("td", "", result.processing_ms === null ? "—" : `${result.processing_ms} ms`),
  );
  qs("#batch-result-body").append(row);
}

function renderPossibleIssues(result) {
  const cell = document.createElement("td");
  const checks = (result.checks || []).filter((check) => check.status !== "match");
  if (!checks.length) {
    cell.append(element("p", "no-issues", "No possible issue detected."));
    return cell;
  }

  const list = element("ul", "issue-list");
  checks.forEach((check) => {
    const expected = check.expected || "not supplied";
    const observed = check.observed || "not confidently detected";
    list.append(
      element(
        "li",
        "",
        `${check.label}: expected ${expected}; observed ${observed}.`,
      ),
    );
  });
  cell.append(list);
  return cell;
}

function possibleIssuesForExport(result) {
  const checks = (result.checks || []).filter((check) => check.status !== "match");
  if (!checks.length) return "No possible issue detected";
  return checks
    .map((check) => {
      const expected = check.expected || "not supplied";
      const observed = check.observed || "not confidently detected";
      return `${check.label}: expected ${expected}; observed ${observed}`;
    })
    .join(" | ");
}

qs("#export-results").addEventListener("click", () => {
  const rows = [
    ["application_id", "status", "possible_issues", "guidance", "processing_ms"],
    ...batchResults.map((result) => [
      result.application_id || "",
      result.overall_status,
      possibleIssuesForExport(result),
      result.summary,
      result.processing_ms ?? "",
    ]),
  ];
  downloadText(
    "ttb-batch-results.csv",
    `${rows.map((row) => row.map(csvEscape).join(",")).join("\n")}\n`,
  );
});

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadText(filename, text) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
