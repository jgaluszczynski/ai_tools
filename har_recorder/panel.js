import { reduceHarFromObject } from "./reduce.js";

const $ = (id) => document.getElementById(id);

const state = {
  recording: false,
  startTime: null,
  stopTime: null,
  entries: [],
  listener: null,
  durationTimer: null,
  statsTimer: null,
  sessionId: 0,
};

function parseFilterTokens(raw) {
  const tokens = (raw || "").trim().split(/\s+/).filter(Boolean);
  const include = [];
  const exclude = [];
  for (const token of tokens) {
    if (token.startsWith("-") && token.length > 1) {
      exclude.push(token.slice(1).toLowerCase());
    } else {
      include.push(token.toLowerCase());
    }
  }
  return { include, exclude };
}

function entryHostname(entry) {
  try {
    return new URL(entry.request.url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function entryUrlLower(entry) {
  return (entry.request?.url || "").toLowerCase();
}

function matchesDomain(entry, domainRaw) {
  const domain = (domainRaw || "").trim().toLowerCase();
  if (!domain) return true;
  return entryHostname(entry).includes(domain);
}

function matchesUrlFilters(entry, urlFilterRaw) {
  const url = entryUrlLower(entry);
  const { include, exclude } = parseFilterTokens(urlFilterRaw);
  for (const token of include) {
    if (!url.includes(token)) return false;
  }
  for (const token of exclude) {
    if (url.includes(token)) return false;
  }
  return true;
}

function filterEntries(entries) {
  const domain = $("domainFilter").value;
  const urlFilter = $("urlFilter").value;
  return entries.filter(
    (entry) =>
      matchesDomain(entry, domain) && matchesUrlFilters(entry, urlFilter),
  );
}

function formatDuration(ms) {
  if (ms == null || Number.isNaN(ms)) return "—";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatBytes(bytes) {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function getReduceOptions() {
  const maxRaw = Number($("maxBodyChars").value);
  const maxBodyChars =
    !Number.isFinite(maxRaw) || maxRaw < 0
      ? 20_000
      : maxRaw === 0
        ? null
        : Math.floor(maxRaw);
  return {
    redactSecrets: $("redactSecrets").checked,
    maxBodyChars,
  };
}

function buildReducedExport(filteredEntries, source = "session.har") {
  const har = { log: { entries: filteredEntries } };
  return reduceHarFromObject(har, {
    source,
    ...getReduceOptions(),
  });
}

function buildRawHar(filteredEntries) {
  return {
    log: {
      version: "1.2",
      creator: {
        name: "HarRecorder",
        version: "1.0.0",
      },
      entries: filteredEntries,
    },
  };
}

function exportBasename() {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `harrecorder_${stamp}`;
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function showToast(message) {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2000);
}

function buildDevToolsFilterString() {
  const parts = [];
  const domain = $("domainFilter").value.trim();
  if (domain) parts.push(`domain:*${domain}*`);
  const raw = ($("urlFilter").value || "").trim();
  if (raw) parts.push(raw);
  return parts.join(" ");
}

function isWithinSessionWindow(startedMs) {
  if (state.startTime == null) return false;
  if (startedMs < state.startTime) return false;
  if (state.stopTime != null && startedMs > state.stopTime) return false;
  return true;
}

function isXhrOrFetch(request) {
  const type = request._resourceType;
  return type === "xhr" || type === "fetch";
}

function buildHarEntry(request, content, encoding) {
  const response = { ...request.response };
  if (content != null) {
    response.content = { ...(response.content || {}) };
    response.content.text = content;
    if (encoding) response.content.encoding = encoding;
  }
  return {
    startedDateTime: request.startedDateTime,
    time: request.time,
    request: request.request,
    response,
    cache: request.cache,
    timings: request.timings,
    serverIPAddress: request.serverIPAddress,
    connection: request.connection,
  };
}

function onRequestFinished(request) {
  if (!state.recording && state.stopTime == null) return;
  if (!isXhrOrFetch(request)) return;

  const startedMs = new Date(request.startedDateTime).getTime();
  if (!isWithinSessionWindow(startedMs)) return;

  const sessionId = state.sessionId;
  request.getContent((content, encoding) => {
    if (sessionId !== state.sessionId) return;
    state.entries.push(buildHarEntry(request, content, encoding));
    render();
  });
}

function setStatus(text, className) {
  const el = $("status");
  el.textContent = text;
  el.className = `status${className ? ` status--${className}` : ""}`;
}

function updateButtons(filtered) {
  $("btnStart").disabled = state.recording;
  $("btnStop").disabled = !state.recording;
  const hasFiltered = filtered.length > 0;
  $("btnDownloadReduced").disabled = !hasFiltered;
  $("btnDownloadRaw").disabled = !hasFiltered;
}

function currentDurationMs() {
  if (state.startTime == null) return null;
  const end = state.recording ? Date.now() : state.stopTime ?? Date.now();
  return end - state.startTime;
}

function updateCountsAndDuration(filtered) {
  $("statEntries").textContent =
    `${filtered.length} / ${state.entries.length}`;
  $("statDuration").textContent = formatDuration(currentDurationMs());
}

function updateExportSize() {
  const filtered = filterEntries(state.entries);
  if (!filtered.length) {
    $("statSize").textContent = "—";
    return;
  }

  try {
    const reduced = buildReducedExport(filtered, "session.har");
    $("statSize").textContent = formatBytes(JSON.stringify(reduced).length);
  } catch {
    $("statSize").textContent = "—";
  }
}

function scheduleExportSizeRefresh() {
  clearTimeout(state.statsTimer);
  state.statsTimer = setTimeout(updateExportSize, 200);
}

function renderEntryList(filtered) {
  const list = $("entryList");
  list.replaceChildren();
  for (const entry of filtered) {
    const li = document.createElement("li");
    li.className = "entry-item";

    const methodEl = document.createElement("span");
    methodEl.className = "entry-method";
    methodEl.textContent = entry.request?.method || "?";

    const status = entry.response?.status;
    const statusEl = document.createElement("span");
    statusEl.className =
      status != null && status >= 400
        ? "entry-status entry-status--error"
        : "entry-status";
    statusEl.textContent = status != null ? String(status) : "?";

    const urlEl = document.createElement("span");
    urlEl.textContent = entry.request?.url || "";

    li.append(
      methodEl,
      document.createTextNode(" "),
      statusEl,
      document.createTextNode(" "),
      urlEl,
    );
    list.appendChild(li);
  }
  $("emptyHint").hidden = filtered.length > 0;
}

function render() {
  const filtered = filterEntries(state.entries);
  renderEntryList(filtered);
  updateCountsAndDuration(filtered);
  updateButtons(filtered);
  scheduleExportSizeRefresh();
}

function startDurationTimer() {
  clearInterval(state.durationTimer);
  state.durationTimer = setInterval(() => {
    if (state.recording) {
      updateCountsAndDuration(filterEntries(state.entries));
    }
  }, 1000);
}

function resetBuffer() {
  state.sessionId += 1;
  state.entries = [];
}

function startRecording() {
  resetBuffer();
  state.recording = true;
  state.startTime = Date.now();
  state.stopTime = null;
  state.listener = onRequestFinished;
  chrome.devtools.network.onRequestFinished.addListener(state.listener);
  setStatus("Recording XHR/fetch…", "recording");
  startDurationTimer();
  render();
}

function stopRecording() {
  if (!state.recording) return;
  state.recording = false;
  state.stopTime = Date.now();
  if (state.listener) {
    chrome.devtools.network.onRequestFinished.removeListener(state.listener);
    state.listener = null;
  }
  clearInterval(state.durationTimer);
  setStatus("Stopped", "stopped");
  render();
}

function clearSession() {
  if (state.recording) stopRecording();
  resetBuffer();
  state.startTime = null;
  state.stopTime = null;
  setStatus("Idle");
  render();
}

function copyDevToolsFilter() {
  const filter = buildDevToolsFilterString();
  if (!filter) {
    showToast("No filters to copy");
    return;
  }
  navigator.clipboard.writeText(filter).then(
    () => showToast("Copied Network filter"),
    () => showToast("Clipboard copy failed"),
  );
}

function downloadReduced() {
  const filtered = filterEntries(state.entries);
  if (!filtered.length) return;
  if (
    !$("redactSecrets").checked &&
    !window.confirm(
      "Redact secrets is off. Export may contain credentials. Continue?",
    )
  ) {
    return;
  }
  const basename = exportBasename();
  const data = buildReducedExport(filtered, `${basename}.har`);
  downloadJson(`${basename}_reduced.json`, data);
}

function downloadRaw() {
  const filtered = filterEntries(state.entries);
  if (!filtered.length) return;
  if (
    !window.confirm(
      "Raw HAR includes cookies, auth headers, and full bodies. Continue?",
    )
  ) {
    return;
  }
  downloadJson(`${exportBasename()}.har`, buildRawHar(filtered));
}

function init() {
  $("btnStart").addEventListener("click", startRecording);
  $("btnStop").addEventListener("click", stopRecording);
  $("btnClear").addEventListener("click", clearSession);
  $("btnCopyFilter").addEventListener("click", copyDevToolsFilter);
  $("btnDownloadReduced").addEventListener("click", downloadReduced);
  $("btnDownloadRaw").addEventListener("click", downloadRaw);

  for (const id of [
    "domainFilter",
    "urlFilter",
    "redactSecrets",
    "maxBodyChars",
  ]) {
    $(id).addEventListener("input", render);
  }

  render();
}

init();
