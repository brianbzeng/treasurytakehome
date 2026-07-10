const qs = (selector, root = document) => root.querySelector(selector);

const MAX_BATCH_LABELS = 100;
const screenForm = qs("#screen-form");
const imageInput = qs("#label-images");
const selectedFiles = qs("#selected-files");
const screenError = qs("#screen-error");
const screenButton = qs("#screen-button");
const maxImageBytes = Number(qs("#main-content").dataset.maxUploadMb) * 1024 * 1024;
const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);

let screeningResults = [];

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

function showError(container, message) {
  container.textContent = message;
  container.classList.remove("hidden");
  container.focus();
}

function hideError(container) {
  container.textContent = "";
  container.classList.add("hidden");
}

function screenItems(files) {
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

function validateFiles(files) {
  if (!files.length) throw new Error("Choose at least one label image.");
  if (files.length > MAX_BATCH_LABELS) {
    throw new Error(`Choose no more than ${MAX_BATCH_LABELS} label images at a time.`);
  }
  for (const file of files) {
    if (!allowedTypes.has(file.type)) {
      throw new Error(`${file.name} is not a supported JPEG, PNG, or WebP image.`);
    }
    if (file.size > maxImageBytes) {
      throw new Error(`${file.name} exceeds the ${Math.round(maxImageBytes / 1024 / 1024)} MB image limit.`);
    }
  }
}

async function submitScreen(item) {
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

screenForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError(screenError);
  screeningResults = [];
  qs("#screen-result-body").replaceChildren();
  qs("#screen-completion").classList.add("hidden");

  try {
    const items = screenItems([...imageInput.files]);
    validateFiles(items.map((item) => item.file));
    await processScreen(items);
  } catch (error) {
    showError(screenError, error.message);
  }
});

async function processScreen(items) {
  const progress = qs("#screen-progress");
  const results = qs("#screen-results");
  const bar = qs("#progress-bar");
  let nextIndex = 0;
  let completed = 0;

  progress.classList.remove("hidden");
  results.classList.remove("hidden");
  screenButton.disabled = true;
  screenButton.textContent = "Screening labels…";
  bar.max = items.length;
  bar.value = 0;
  updateProgress(completed, items.length);

  async function worker() {
    while (nextIndex < items.length) {
      const item = items[nextIndex];
      nextIndex += 1;
      try {
        const result = await submitScreen(item);
        screeningResults.push(result);
        appendScreenRow(result);
      } catch (error) {
        const failure = {
          label_id: item.labelId,
          overall_status: "unable",
          request_failed: true,
          summary: error.message,
          processing_ms: null,
          checks: [],
        };
        const resultIndex = screeningResults.push(failure) - 1;
        appendScreenRow(failure, async () => {
          try {
            const retryResult = await submitScreen(item);
            screeningResults[resultIndex] = retryResult;
            return retryResult;
          } catch (retryError) {
            failure.summary = retryError.message;
            renderCompletion();
            throw retryError;
          }
        });
      }
      completed += 1;
      bar.value = completed;
      updateProgress(completed, items.length);
    }
  }

  try {
    await Promise.all([worker(), worker()]);
  } finally {
    screenButton.disabled = false;
    screenButton.textContent = "Start label screen";
    renderCompletion();
  }
}

function updateProgress(completed, total) {
  qs("#progress-text").textContent =
    completed === total
      ? `${total} of ${total} labels complete.`
      : `${completed} of ${total} labels complete. You may review finished results below.`;
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

function appendScreenRow(result, retry = null) {
  const row = document.createElement("tr");
  const statusNames = {
    match: "No possible review items",
    attention: "Possible review items",
    unable: "Human review required",
  };
  const statusName = result.request_failed
    ? "Processing failed"
    : statusNames[result.overall_status];
  const guidance = element("td", "", result.summary);
  if (retry) guidance.append(renderRetryButton(retry, row));
  row.append(
    element("td", "", result.label_id || "Unnamed label"),
    element("td", "", statusName),
    renderPossibleItems(result),
    guidance,
    element("td", "", result.processing_ms === null ? "—" : `${result.processing_ms} ms`),
  );
  qs("#screen-result-body").append(row);
  return row;
}

function renderRetryButton(retry, originalRow) {
  const container = element("div", "batch-retry");
  const button = element("button", "secondary-button", "Retry this label");
  const message = element("p", "batch-retry-message hidden");
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Retrying…";
    message.classList.add("hidden");
    try {
      const result = await retry();
      const replacement = appendScreenRow(result);
      originalRow.replaceWith(replacement);
      renderCompletion();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Retry this label";
      message.textContent = `Retry failed: ${error.message}`;
      message.classList.remove("hidden");
    }
  });
  container.append(button, message);
  return container;
}

function renderPossibleItems(result) {
  const cell = document.createElement("td");
  if (result.request_failed) {
    cell.append(element("p", "no-issues", "No screening result was produced."));
    return cell;
  }
  const checks = (result.checks || []).filter((check) => check.status === "review");
  if (!checks.length) {
    cell.append(element("p", "no-issues", "No possible review items identified."));
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

function formatLabelIds(results) {
  const ids = results.map((result) => result.label_id || "an unnamed label");
  if (ids.length === 1) return ids[0];
  if (ids.length === 2) return `${ids[0]} and ${ids[1]}`;
  return `${ids.slice(0, -1).join(", ")}, and ${ids.at(-1)}`;
}

function renderCompletion() {
  if (!screeningResults.length) return;
  const possibleItems = screeningResults.filter(
    (result) => result.overall_status === "attention",
  );
  const uncertain = screeningResults.filter(
    (result) => result.overall_status === "unable" && !result.request_failed,
  );
  const failed = screeningResults.filter((result) => result.request_failed);
  const copy = [];

  if (possibleItems.length) {
    copy.push(
      `Labels ${formatLabelIds(possibleItems)} ${possibleItems.length === 1 ? "has" : "have"} possible review items.`,
    );
  }
  if (uncertain.length) {
    copy.push(
      `Labels ${formatLabelIds(uncertain)} ${uncertain.length === 1 ? "requires" : "require"} human review because the automated screen could not verify all visible information.`,
    );
  }
  if (failed.length) {
    copy.push(
      `Labels ${formatLabelIds(failed)} could not be processed and can be retried.`,
    );
  }
  if (!copy.length) {
    copy.push(`No possible review items were identified across ${screeningResults.length} labels.`);
  }
  copy.push("You can continue to applications when ready.");

  qs("#screen-completion-copy").textContent = copy.join(" ");
  qs("#screen-completion").classList.remove("hidden");
}

qs("#print-results").addEventListener("click", () => window.print());
