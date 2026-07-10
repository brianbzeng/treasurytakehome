const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

const MAX_QUICK_LABELS = 100;
const MAX_COMPARE_ROWS = 300;
const maxImageBytes = Number(qs("#main-content").dataset.maxUploadMb) * 1024 * 1024;
const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const beverageTypes = new Set(["distilled_spirits", "wine", "malt_beverage"]);

let quickResults = [];
let comparisonResults = [];
let activeWorkflow = null;

function beginWorkflow(mode) {
  if (activeWorkflow) {
    throw new Error("Wait for the current screening batch to finish before starting another.");
  }
  activeWorkflow = mode;
  qs("#screen-button").disabled = true;
  qs("#compare-button").disabled = true;
  qsa(".batch-retry button").forEach((button) => {
    button.disabled = true;
  });
}

function endWorkflow(mode) {
  if (activeWorkflow !== mode) return;
  activeWorkflow = null;
  qs("#screen-button").disabled = false;
  qs("#compare-button").disabled = false;
  qsa(".batch-retry button").forEach((button) => {
    button.disabled = false;
  });
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function externalLink(url, label) {
  const link = element("a", "text-link", label);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

function validateImage(file) {
  if (!allowedTypes.has(file.type)) {
    throw new Error(`${file.name} is not a supported JPEG, PNG, or WebP image.`);
  }
  if (file.size > maxImageBytes) {
    throw new Error(
      `${file.name} exceeds the ${Math.round(maxImageBytes / 1024 / 1024)} MB image limit.`,
    );
  }
}

function renderRetryControl(buttonLabel, retry, onSuccess) {
  const container = element("div", "batch-retry");
  const button = element("button", "secondary-button", buttonLabel);
  const message = element("p", "batch-retry-message hidden");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  button.type = "button";
  button.disabled = Boolean(activeWorkflow);
  button.addEventListener("click", async () => {
    if (activeWorkflow) {
      message.textContent = "Wait for the current screening request to finish before retrying.";
      message.classList.remove("hidden");
      return;
    }
    beginWorkflow("retry");
    button.textContent = "Retrying…";
    message.classList.add("hidden");
    try {
      const result = await retry();
      onSuccess(result);
    } catch (error) {
      button.disabled = false;
      button.textContent = buttonLabel;
      message.textContent = `Retry failed: ${error.message}`;
      message.classList.remove("hidden");
    } finally {
      endWorkflow("retry");
    }
  });
  container.append(button, message);
  return container;
}

function selectMode(mode) {
  const quick = mode === "quick";
  qs("#quick-tab").classList.toggle("active", quick);
  qs("#compare-tab").classList.toggle("active", !quick);
  qs("#quick-tab").setAttribute("aria-selected", String(quick));
  qs("#compare-tab").setAttribute("aria-selected", String(!quick));
  qs("#quick-tab").tabIndex = quick ? 0 : -1;
  qs("#compare-tab").tabIndex = quick ? -1 : 0;
  qs("#quick-panel").classList.toggle("hidden", !quick);
  qs("#compare-panel").classList.toggle("hidden", quick);
  (quick ? qs("#quick-tab") : qs("#compare-tab")).focus();
}

qs("#quick-tab").addEventListener("click", () => selectMode("quick"));
qs("#compare-tab").addEventListener("click", () => selectMode("compare"));
qsa(".mode-button").forEach((button) => {
  button.addEventListener("keydown", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "Home") selectMode("quick");
      else if (event.key === "End") selectMode("compare");
      else selectMode(button.id === "quick-tab" ? "compare" : "quick");
    }
  });
});

// Quick image-only diagnostic.
const quickForm = qs("#screen-form");
const quickImages = qs("#label-images");

quickImages.addEventListener("change", () => {
  qs("#selected-files").replaceChildren(
    ...[...quickImages.files].map((file) =>
      element("li", "", `${file.name} (${formatBytes(file.size)})`),
    ),
  );
});

function quickItems(files) {
  const seenNames = new Map();
  return files.map((file) => {
    const count = (seenNames.get(file.name) || 0) + 1;
    seenNames.set(file.name, count);
    return {
      file,
      labelId: count === 1 ? file.name : `${file.name} (${count})`,
    };
  });
}

function validateQuickItems(items) {
  if (!items.length) throw new Error("Choose at least one label image.");
  if (items.length > MAX_QUICK_LABELS) {
    throw new Error(`Choose no more than ${MAX_QUICK_LABELS} label images at a time.`);
  }
  items.forEach((item) => validateImage(item.file));
}

async function submitQuickScreen(item) {
  const payload = new FormData();
  payload.append("label_id", item.labelId);
  payload.append("image", item.file);
  const response = await fetch("/api/screen", { method: "POST", body: payload });
  const body = await response.json().catch(() => ({
    error: "The server returned an unreadable response.",
  }));
  if (!response.ok) throw new Error(body.error || "The label could not be screened.");
  return body;
}

quickForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError(qs("#screen-error"));
  if (activeWorkflow) {
    showError(
      qs("#screen-error"),
      "Wait for the current screening batch to finish before starting another.",
    );
    return;
  }
  quickResults = [];
  qs("#screen-result-body").replaceChildren();
  qs("#screen-completion").classList.add("hidden");
  try {
    const items = quickItems([...quickImages.files]);
    validateQuickItems(items);
    await processQuickItems(items);
  } catch (error) {
    showError(qs("#screen-error"), error.message);
  }
});

async function processQuickItems(items) {
  const button = qs("#screen-button");
  const bar = qs("#screen-progress-bar");
  let nextIndex = 0;
  let completed = 0;
  beginWorkflow("quick");
  qs("#screen-progress").classList.remove("hidden");
  qs("#screen-results").classList.remove("hidden");
  button.textContent = "Scanning labels…";
  bar.max = items.length;
  bar.value = 0;
  updateQuickProgress(completed, items.length);

  async function worker() {
    while (nextIndex < items.length) {
      const item = items[nextIndex];
      nextIndex += 1;
      try {
        const result = await submitQuickScreen(item);
        quickResults.push(result);
        appendQuickRow(result);
      } catch (error) {
        const failure = {
          label_id: item.labelId,
          overall_status: "unable",
          request_failed: true,
          summary: error.message,
          processing_ms: null,
          checks: [],
        };
        const resultIndex = quickResults.push(failure) - 1;
        appendQuickRow(failure, async () => {
          try {
            const retried = await submitQuickScreen(item);
            quickResults[resultIndex] = retried;
            return retried;
          } catch (retryError) {
            failure.summary = retryError.message;
            renderQuickSummary();
            throw retryError;
          }
        });
      }
      completed += 1;
      bar.value = completed;
      updateQuickProgress(completed, items.length);
    }
  }

  try {
    await Promise.all([worker(), worker()]);
  } finally {
    endWorkflow("quick");
    button.textContent = "Start quick scan";
    renderQuickSummary();
  }
}

function updateQuickProgress(completed, total) {
  qs("#screen-progress-text").textContent = completed === total
    ? `${total} of ${total} labels complete.`
    : `${completed} of ${total} labels complete. You may review finished results below.`;
}

function appendQuickRow(result, retry = null) {
  const row = document.createElement("tr");
  const names = {
    match: "No major review item identified",
    attention: "Possible major issue",
    unable: "Human review required",
  };
  const guidance = element("td", "", result.summary);
  if (retry) {
    guidance.append(
      renderRetryControl("Retry this label", retry, (retried) => {
        row.replaceWith(appendQuickRow(retried));
        renderQuickSummary();
      }),
    );
  }
  row.append(
    element("td", "", result.label_id || "Unnamed label"),
    element("td", "", result.request_failed ? "Processing failed" : names[result.overall_status]),
    renderQuickItems(result),
    guidance,
    element("td", "", result.processing_ms === null ? "—" : `${result.processing_ms} ms`),
  );
  qs("#screen-result-body").append(row);
  return row;
}

function renderQuickItems(result) {
  const cell = document.createElement("td");
  if (result.request_failed) {
    cell.append(element("p", "no-issues", "No diagnostic result was produced."));
    return cell;
  }
  const checks = (result.checks || []).filter((check) => check.status === "review");
  if (!checks.length) {
    cell.append(element("p", "no-issues", "No major review item identified."));
    return cell;
  }
  const list = element("ul", "issue-list");
  checks.forEach((check) => {
    const observed = check.observed || "Not confidently located";
    const item = element("li", "", `${check.label}: ${check.explanation} Observed: ${observed}.`);
    if (check.guidance_url) {
      item.append(
        document.createTextNode(" "),
        externalLink(check.guidance_url, check.guidance_title || "TTB guidance"),
      );
    }
    list.append(item);
  });
  cell.append(list);
  return cell;
}

function formatResultIds(results, key, fallback) {
  const ids = results.map((result) => result[key] || fallback);
  if (ids.length === 1) return ids[0];
  if (ids.length === 2) return `${ids[0]} and ${ids[1]}`;
  return `${ids.slice(0, -1).join(", ")}, and ${ids.at(-1)}`;
}

function renderQuickSummary() {
  if (!quickResults.length) return;
  const possible = quickResults.filter((result) => result.overall_status === "attention");
  const uncertain = quickResults.filter(
    (result) => result.overall_status === "unable" && !result.request_failed,
  );
  const failed = quickResults.filter((result) => result.request_failed);
  const copy = [];
  if (possible.length) {
    copy.push(
      `${possible.length === 1 ? "Label" : "Labels"} ${formatResultIds(possible, "label_id", "an unnamed label")} ${possible.length === 1 ? "may have a major review item" : "may have major review items"}.`,
    );
  }
  if (uncertain.length) {
    copy.push(
      `${uncertain.length === 1 ? "Label" : "Labels"} ${formatResultIds(uncertain, "label_id", "an unnamed label")} ${uncertain.length === 1 ? "requires" : "require"} human review.`,
    );
  }
  if (failed.length) {
    copy.push(
      `${failed.length === 1 ? "Label" : "Labels"} ${formatResultIds(failed, "label_id", "an unnamed label")} could not be processed and can be retried.`,
    );
  }
  if (!copy.length) {
    copy.push(
      `No major review items were identified across ${quickResults.length} ${quickResults.length === 1 ? "label" : "labels"}.`,
    );
  }
  copy.push("Use application comparison when you need field-by-field discrepancy screening.");
  qs("#screen-completion-copy").textContent = copy.join(" ");
  qs("#screen-completion").classList.remove("hidden");
}

// CSV-backed application comparison.
const templateHeaders = [
  "id", "beverage_type", "brand_name", "class_type", "abv", "proof", "net_contents",
  "producer_name_address", "country_of_origin", "image_filename",
];
const templateRow = [
  "APP-001", "distilled_spirits", "Old Tom Distillery", "Kentucky Straight Bourbon Whiskey",
  "45", "90", "750 mL", "Old Tom Distillery, Louisville KY", "", "old-tom-front.jpg",
];

qs("#template-link").addEventListener("click", (event) => {
  event.preventDefault();
  downloadText(
    "ttb-batch-template.csv",
    `${templateHeaders.map(csvEscape).join(",")}\n${templateRow.map(csvEscape).join(",")}\n`,
  );
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
  const headers = matrix[0].map((header) =>
    header.replace(/^\uFEFF/, "").trim().toLowerCase(),
  );
  return matrix.slice(1).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])),
  );
}

function validateComparisonRows(rows) {
  if (rows.length > MAX_COMPARE_ROWS) {
    throw new Error(`A comparison batch may contain no more than ${MAX_COMPARE_ROWS} applications.`);
  }
  rows.forEach((row, index) => {
    for (const header of templateHeaders.filter((name) => name !== "beverage_type")) {
      if (!(header in row)) throw new Error(`Missing required CSV column: ${header}`);
    }
    const beverageType = row.beverage_type || "distilled_spirits";
    if (!beverageTypes.has(beverageType)) {
      throw new Error(`Row ${index + 2} has an invalid beverage_type.`);
    }
    for (const field of ["id", "brand_name", "class_type", "net_contents", "producer_name_address", "image_filename"]) {
      if (!row[field]) throw new Error(`Row ${index + 2} is missing ${field}.`);
    }
    if (beverageType === "distilled_spirits" && !row.abv) {
      throw new Error(`Row ${index + 2} is missing ABV for a distilled spirit.`);
    }
    if (row.abv) {
      const abv = Number(row.abv);
      if (!Number.isFinite(abv) || abv <= 0 || abv > 100) {
        throw new Error(`Row ${index + 2} has an invalid ABV.`);
      }
    }
    if (row.proof) {
      const proof = Number(row.proof);
      if (!Number.isFinite(proof) || proof <= 0 || proof > 200) {
        throw new Error(`Row ${index + 2} has an invalid proof.`);
      }
    }
  });
}

async function submitComparison(application, image) {
  const payload = new FormData();
  payload.append("application", JSON.stringify(application));
  payload.append("images", image);
  const response = await fetch("/api/review", { method: "POST", body: payload });
  const body = await response.json().catch(() => ({
    error: "The server returned an unreadable response.",
  }));
  if (!response.ok) throw new Error(body.error || "The application could not be compared.");
  return body;
}

qs("#compare-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError(qs("#compare-error"));
  if (activeWorkflow) {
    showError(
      qs("#compare-error"),
      "Wait for the current screening batch to finish before starting another.",
    );
    return;
  }
  comparisonResults = [];
  qs("#compare-result-body").replaceChildren();
  qs("#compare-completion").classList.add("hidden");
  try {
    const csvFile = qs("#compare-csv").files[0];
    const imageFiles = [...qs("#compare-images").files];
    if (!csvFile) throw new Error("Choose a CSV manifest.");
    imageFiles.forEach(validateImage);
    const rows = parseCsv(await csvFile.text());
    validateComparisonRows(rows);
    const imagesByName = new Map(imageFiles.map((file) => [file.name, file]));
    rows.forEach((row) => {
      if (!imagesByName.has(row.image_filename)) {
        throw new Error(`Image not found for ${row.id}: ${row.image_filename}`);
      }
    });
    await processComparisons(rows, imagesByName);
  } catch (error) {
    showError(qs("#compare-error"), error.message);
  }
});

function applicationFromRow(row) {
  const beverageType = row.beverage_type || "distilled_spirits";
  return {
    application_id: row.id,
    beverage_type: beverageType,
    brand_name: row.brand_name,
    class_type: row.class_type,
    abv: row.abv ? Number(row.abv) : null,
    proof: beverageType === "distilled_spirits" && row.proof ? Number(row.proof) : null,
    net_contents: row.net_contents,
    producer_name_address: row.producer_name_address,
    country_of_origin: row.country_of_origin || null,
  };
}

async function processComparisons(rows, imagesByName) {
  const button = qs("#compare-button");
  const bar = qs("#compare-progress-bar");
  let nextIndex = 0;
  let completed = 0;
  beginWorkflow("compare");
  qs("#compare-progress").classList.remove("hidden");
  qs("#compare-results").classList.remove("hidden");
  button.textContent = "Comparing applications…";
  bar.max = rows.length;
  bar.value = 0;
  updateComparisonProgress(completed, rows.length);

  async function worker() {
    while (nextIndex < rows.length) {
      const sourceRow = rows[nextIndex];
      nextIndex += 1;
      const application = applicationFromRow(sourceRow);
      const image = imagesByName.get(sourceRow.image_filename);
      try {
        const result = await submitComparison(application, image);
        comparisonResults.push(result);
        appendComparisonRow(result);
      } catch (error) {
        const failure = {
          application_id: sourceRow.id,
          overall_status: "unable",
          request_failed: true,
          summary: error.message,
          processing_ms: null,
          checks: [],
        };
        const resultIndex = comparisonResults.push(failure) - 1;
        appendComparisonRow(failure, async () => {
          try {
            const retried = await submitComparison(application, image);
            comparisonResults[resultIndex] = retried;
            return retried;
          } catch (retryError) {
            failure.summary = retryError.message;
            renderComparisonSummary();
            throw retryError;
          }
        });
      }
      completed += 1;
      bar.value = completed;
      updateComparisonProgress(completed, rows.length);
    }
  }

  try {
    await Promise.all([worker(), worker()]);
  } finally {
    endWorkflow("compare");
    button.textContent = "Start application comparison";
    renderComparisonSummary();
  }
}

function updateComparisonProgress(completed, total) {
  qs("#compare-progress-text").textContent = completed === total
    ? `${total} of ${total} applications complete.`
    : `${completed} of ${total} applications complete. You may review finished results below.`;
}

function appendComparisonRow(result, retry = null) {
  const row = document.createElement("tr");
  const names = {
    match: "Matches",
    attention: "Needs attention",
    unable: "Human review required",
  };
  const guidance = element("td", "", result.summary);
  if (retry) {
    guidance.append(
      renderRetryControl("Retry this application", retry, (retried) => {
        row.replaceWith(appendComparisonRow(retried));
        renderComparisonSummary();
      }),
    );
  }
  row.append(
    element("td", "", result.application_id || "Not supplied"),
    element("td", "", result.request_failed ? "Processing failed" : names[result.overall_status]),
    renderComparisonFindings(result),
    guidance,
    element("td", "", result.processing_ms === null ? "—" : `${result.processing_ms} ms`),
  );
  qs("#compare-result-body").append(row);
  return row;
}

function renderComparisonFindings(result) {
  const cell = document.createElement("td");
  if (result.request_failed) {
    cell.append(element("p", "no-issues", "No comparison result was produced."));
    return cell;
  }
  if (result.overall_status === "match") {
    cell.append(element("p", "no-issues", "No discrepancies identified."));
    return cell;
  }
  const checks = (result.checks || []).filter((check) => check.status !== "match");
  const list = element("ul", "issue-list");
  checks.forEach((check) => {
    const expected = check.expected || "not supplied";
    const observed = check.observed || "not confidently detected";
    const item = element("li", "", `${check.label}: expected ${expected}; observed ${observed}.`);
    if (check.guidance_url) {
      item.append(
        document.createTextNode(" "),
        externalLink(check.guidance_url, check.guidance_title || "TTB guidance"),
      );
    }
    list.append(item);
  });
  cell.append(list);
  return cell;
}

function renderComparisonSummary() {
  if (!comparisonResults.length) return;
  const discrepancies = comparisonResults.filter((result) => result.overall_status === "attention");
  const uncertain = comparisonResults.filter(
    (result) => result.overall_status === "unable" && !result.request_failed,
  );
  const failed = comparisonResults.filter((result) => result.request_failed);
  const copy = [];
  if (discrepancies.length) {
    copy.push(
      `${discrepancies.length === 1 ? "Application" : "Applications"} ${formatResultIds(discrepancies, "application_id", "an application")} ${discrepancies.length === 1 ? "has" : "have"} discrepancies.`,
    );
  }
  if (uncertain.length) {
    copy.push(
      `${uncertain.length === 1 ? "Application" : "Applications"} ${formatResultIds(uncertain, "application_id", "an application")} ${uncertain.length === 1 ? "requires" : "require"} human review.`,
    );
  }
  if (failed.length) {
    copy.push(
      `${failed.length === 1 ? "Application" : "Applications"} ${formatResultIds(failed, "application_id", "an application")} could not be processed and can be retried.`,
    );
  }
  if (!copy.length) {
    copy.push(
      comparisonResults.length === 1
        ? "The application matched the supplied application data."
        : `All ${comparisonResults.length} applications matched the supplied application data.`,
    );
  }
  copy.push("You can continue to applications when ready.");
  qs("#compare-completion-copy").textContent = copy.join(" ");
  qs("#compare-completion").classList.remove("hidden");
}

qs("#print-screen-results").addEventListener("click", () => window.print());
qs("#print-compare-results").addEventListener("click", () => window.print());

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
