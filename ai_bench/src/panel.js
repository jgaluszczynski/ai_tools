import { DEFAULT_METRICS } from "./labels.js";
import { filterMetricsForDisplay, mean, localDateKey, sortFavoritesByRank } from "./parse.js";
import { renderSparkline } from "./sparkline.js";
import {
  buildScoreScale,
  formatDisplayValue,
  valueColor,
} from "./colors.js";

const $ = (id) => document.getElementById(id);

function initSettingsButton() {
  const btn = $("openSettings");
  if (!btn || btn.firstChild) return;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const outer = document.createElementNS("http://www.w3.org/2000/svg", "path");
  outer.setAttribute(
    "d",
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
  );
  outer.setAttribute("fill", "none");
  outer.setAttribute("stroke", "currentColor");
  outer.setAttribute("stroke-width", "1.75");
  const teeth = document.createElementNS("http://www.w3.org/2000/svg", "path");
  teeth.setAttribute(
    "d",
    "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z",
  );
  teeth.setAttribute("fill", "none");
  teeth.setAttribute("stroke", "currentColor");
  teeth.setAttribute("stroke-width", "1.75");
  teeth.setAttribute("stroke-linecap", "round");
  teeth.setAttribute("stroke-linejoin", "round");
  svg.appendChild(teeth);
  svg.appendChild(outer);
  btn.appendChild(svg);
  btn.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
}

function collectScoreScale(latest) {
  const scores = [];
  for (const row of [...getTopRows(latest), ...(latest.favorites || [])]) {
    const m = row.metrics || {};
    if (typeof m.score === "number") scores.push(m.score);
    if (typeof m.current_score === "number") scores.push(m.current_score);
    for (const s of row.history_tail || []) scores.push(s);
  }
  return buildScoreScale(scores);
}

function appendChip(chips, label, val, scoreScale) {
  const chip = document.createElement("span");
  chip.className = "chip";
  const lab = document.createElement("span");
  lab.className = "chip-label";
  lab.textContent = `${label}=`;
  const num = document.createElement("span");
  num.className = "chip-value";
  num.textContent = formatDisplayValue(val);
  num.style.color = valueColor(label, val, scoreScale);
  chip.appendChild(lab);
  chip.appendChild(num);
  chips.appendChild(chip);
}

function prevDateKey() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return localDateKey(d);
}

function getTopRows(latest) {
  return latest.top || latest.top5 || [];
}

function getTopIds(latest) {
  return latest.top_ids || latest.top5_ids || getTopRows(latest).map((r) => r.id);
}

function findPrevRow(snapshots, id, name) {
  const prevKey = prevDateKey();
  const snap = snapshots?.[prevKey];
  if (!snap) return null;
  const all = [...getTopRows(snap), ...(snap.favorites || [])];
  return all.find((r) => (id && r.id === id) || r.name === name) || null;
}

function formatDelta(cur, prev, label) {
  if (prev == null || cur == null) return null;
  const c = Number(cur);
  const p = Number(prev);
  if (!Number.isFinite(c) || !Number.isFinite(p)) return null;
  const d = c - p;
  if (d === 0) return null;
  const cls = d > 0 ? "delta-up" : "delta-down";
  const sign = d > 0 ? "+" : "";
  return { text: `${label}${sign}${d.toFixed(1)}`, cls };
}

function buildVarianceFooter(latest, snapshots) {
  const lines = [];
  const prevKey = prevDateKey();
  const prevSnap = snapshots?.[prevKey];
  const topCount = latest.topCount || getTopRows(latest).length || 5;
  if (!prevSnap) {
    lines.push({ text: "No prior day snapshot for variance.", cls: "" });
    return lines;
  }

  const prevIds = new Set(getTopIds(prevSnap));
  const curIds = new Set(getTopIds(latest));
  for (const id of curIds) {
    if (!prevIds.has(id)) {
      const row = getTopRows(latest).find((r) => r.id === id);
      if (row) lines.push({ text: `new in TOP ${topCount}: ${row.name}`, cls: "" });
    }
  }
  for (const id of prevIds) {
    if (!curIds.has(id)) {
      const row = getTopRows(prevSnap).find((r) => r.id === id);
      if (row) lines.push({ text: `dropped from TOP ${topCount}: ${row.name}`, cls: "" });
    }
  }

  const seen = new Set();
  const models = [...getTopRows(latest), ...(latest.favorites || [])];
  for (const row of models) {
    const key = row.id || row.name;
    if (seen.has(key)) continue;
    seen.add(key);
    const prev = findPrevRow(snapshots, row.id, row.name);
    if (!prev) continue;
    const parts = [];
    const ds = formatDelta(row.metrics?.score, prev.metrics?.score, "Δscore=");
    if (ds) parts.push(ds);
    const dse = formatDelta(
      row.metrics?.standard_error,
      prev.metrics?.standard_error,
      "Δstandard_error=",
    );
    if (dse) parts.push(dse);
    const curHm = mean(row.history_tail || []);
    const prevHm = mean(prev.history_tail || []);
    if (curHm != null && prevHm != null) {
      const dh = curHm - prevHm;
      if (dh !== 0) {
        parts.push({
          text: `Δhistory_mean=${dh > 0 ? "+" : ""}${dh.toFixed(2)}`,
          cls: dh > 0 ? "delta-up" : "delta-down",
        });
      }
    }
    if (row.metrics?.trend !== prev.metrics?.trend) {
      parts.push({ text: `trend: ${prev.metrics?.trend} → ${row.metrics?.trend}`, cls: "" });
    }
    if (parts.length) {
      const inner = parts.map((p) => p.text).join(" ");
      lines.push({ text: `${row.name}: ${inner}`, cls: parts[0]?.cls || "" });
    }
  }
  return lines.length ? lines : [{ text: "No metric changes vs yesterday.", cls: "" }];
}

function renderRow(container, row, opts) {
  const { rank, favNames, excludedMetrics, showRank, compact, scoreScale } = opts;
  const el = document.createElement("div");
  el.className = "row";

  const head = document.createElement("div");
  head.className = "row-head";

  const titleRow = document.createElement("div");
  titleRow.className = compact ? "row-title" : "row-title row-title--inline";

  if (showRank && rank != null) {
    const rankEl = document.createElement("span");
    rankEl.className = "rank";
    rankEl.textContent = `#${rank}`;
    titleRow.appendChild(rankEl);
  }

  const nameEl = document.createElement("span");
  nameEl.className = "name";
  if (row.missing) nameEl.classList.add("name--missing");
  else if (Number(rank) === 1) nameEl.classList.add("name--rank-1");
  else if (compact || favNames.has(row.name)) nameEl.classList.add("name--fav");
  nameEl.textContent = row.name;
  titleRow.appendChild(nameEl);
  head.appendChild(titleRow);

  const sparkHost = document.createElement("div");
  sparkHost.className = "sparkline";
  renderSparkline(sparkHost, row.history_tail || row.historyTail || []);
  head.appendChild(sparkHost);

  el.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "chips";
  const pairs = filterMetricsForDisplay(row.metrics || {}, excludedMetrics, DEFAULT_METRICS);
  const limit = compact ? 4 : pairs.length;
  for (const [label, val] of pairs.slice(0, limit)) {
    appendChip(chips, label, val, scoreScale);
  }
  el.appendChild(chips);
  container.appendChild(el);
}

function render(latest, snapshots, config, lastError) {
  const favNames = new Set((latest.favorites || []).map((f) => f.name).filter(Boolean));
  const excludedMetrics = config.excludedMetrics || [];
  const topRows = getTopRows(latest);
  const topCount = latest.topCount || topRows.length || 5;
  const scoreScale = collectScoreScale(latest);

  $("topTitle").textContent = `TOP ${topCount}:`;
  $("topList").replaceChildren();
  $("favorites").replaceChildren();

  topRows.forEach((row, i) => {
    const rank = row.rank != null ? row.rank : i + 1;
    renderRow($("topList"), row, {
      rank,
      favNames,
      excludedMetrics,
      showRank: true,
      compact: false,
      scoreScale,
    });
  });

  const favs = sortFavoritesByRank(latest.favorites || []);
  if (!favs.length) {
    $("fav-hint").hidden = false;
  } else {
    $("fav-hint").hidden = true;
    favs.forEach((row) => {
      renderRow($("favorites"), row, {
        rank: row.rank,
        favNames,
        excludedMetrics,
        showRank: row.rank != null,
        compact: true,
        scoreScale,
      });
    });
  }

  const meta = $("meta");
  const when = latest.fetchedAt || "";
  const stale = topRows.some((r) => r.metrics?.is_stale === true);
  meta.textContent = `${when ? new Date(when).toLocaleString() : "—"}${stale ? " · stale data" : ""}`;

  const err = $("error");
  if (lastError) {
    err.hidden = false;
    err.textContent = lastError;
  } else {
    err.hidden = true;
    err.textContent = "";
  }

  const footer = $("variance");
  footer.replaceChildren();
  for (const line of buildVarianceFooter(latest, snapshots)) {
    const p = document.createElement("p");
    p.className = "variance-line" + (line.cls ? ` ${line.cls}` : "");
    p.textContent = line.text;
    footer.appendChild(p);
  }
}

async function loadPanel() {
  const config = await chrome.storage.sync.get([
    "excludedMetrics",
    "topCount",
  ]);
  const excludedRaw = config.excludedMetrics || "";
  const excludedMetrics =
    typeof excludedRaw === "string"
      ? excludedRaw.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
      : [];

  const res = await chrome.runtime.sendMessage({ type: "GET_LATEST" });
  if (!res?.ok || !res.latest) {
    $("meta").textContent = "Loading…";
    const refresh = await chrome.runtime.sendMessage({ type: "REFRESH" });
    if (refresh?.ok && refresh.latest) {
      const again = await chrome.runtime.sendMessage({ type: "GET_LATEST" });
      render(again.latest, again.snapshots || {}, { excludedMetrics }, again.lastError);
    } else {
      $("error").hidden = false;
      $("error").textContent = refresh?.error || res?.lastError || "No data yet";
    }
    return;
  }
  render(res.latest, res.snapshots || {}, { excludedMetrics }, res.lastError);
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "UPDATED") loadPanel();
});

document.addEventListener("DOMContentLoaded", () => {
  initSettingsButton();
  loadPanel();
  chrome.runtime.sendMessage({ type: "REFRESH" }).catch(() => {});
});
