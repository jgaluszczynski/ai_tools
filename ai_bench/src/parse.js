import {
  MODEL_SCORE_LABELS,
  DEFAULT_METRICS,
  MAX_MODELS,
  MAX_FAVORITES,
  MAX_NAME_LEN,
  MIN_TOP_COUNT,
  MAX_TOP_COUNT,
  DEFAULT_TOP_COUNT,
} from "./labels.js";

const FAV_LEGACY_RE = /^#?\d*\s*(.+)$/;

export function formatPythonValue(v) {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return String(v);
}

export function normalizeMetrics(model, excludedLabels = []) {
  const exclude = new Set(excludedLabels);
  const metrics = {};
  for (const [apiKey, label] of Object.entries(MODEL_SCORE_LABELS)) {
    if (exclude.has(label)) continue;
    if (!(apiKey in model)) continue;
    metrics[label] = model[apiKey];
  }
  return metrics;
}

export function extractHistoryTail(historyMap, id, n = 7) {
  if (!historyMap || typeof historyMap !== "object") return [];
  const hist = historyMap[String(id)];
  if (!Array.isArray(hist)) return [];
  const tail = hist.slice(-n);
  const scores = [];
  for (const pt of tail) {
    if (!pt || typeof pt !== "object") continue;
    const score = pt.score;
    if (typeof score === "number" && Number.isFinite(score)) scores.push(score);
  }
  return scores;
}

export function parseFavoriteNames(input) {
  const warnings = [];
  let names = [];
  if (Array.isArray(input)) names = input;
  else if (typeof input === "string" && input.trim()) names = migrateFavoritesText(input);
  const seen = new Set();
  const favorites = [];
  for (const raw of names.slice(0, MAX_FAVORITES)) {
    const name = String(raw).trim().slice(0, MAX_NAME_LEN);
    if (!name || seen.has(name)) continue;
    seen.add(name);
    favorites.push({ name });
  }
  return { favorites, warnings };
}

export function migrateFavoritesText(text) {
  const out = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const m = FAV_LEGACY_RE.exec(t);
    const name = (m ? m[1] : t).trim();
    if (name) out.push(name);
  }
  return out;
}

export function buildRankByName(sortedRows) {
  const rankByName = new Map();
  sortedRows.forEach((row, i) => rankByName.set(row.name, i + 1));
  return rankByName;
}


export function namesFromApiModels(json) {
  if (!Array.isArray(json)) return [];
  return json.map((m) => (m && m.name ? String(m.name) : "")).filter(Boolean);
}

export function mergeModelNameLists(...lists) {
  const seen = new Set();
  const out = [];
  for (const list of lists) {
    if (!Array.isArray(list)) continue;
    for (const name of list) {
      const n = String(name).trim();
      if (!n || seen.has(n)) continue;
      seen.add(n);
      out.push(n);
    }
  }
  return out.sort((a, b) => a.localeCompare(b));
}

export function rankByNameToObject(rankByName) {
  if (!rankByName) return {};
  if (rankByName instanceof Map) return Object.fromEntries(rankByName);
  return rankByName;
}

export function parseDashboard(raw, opts = {}) {
  const historyBarCount = clampInt(opts.historyBarCount ?? 7, 5, 24);
  const excludedMetrics = Array.isArray(opts.excludedMetrics) ? opts.excludedMetrics : [];
  const topCount = clampInt(opts.topCount ?? DEFAULT_TOP_COUNT, MIN_TOP_COUNT, MAX_TOP_COUNT);

  if (!raw || typeof raw !== "object") return { error: "Invalid JSON root" };
  const root = raw;
  if (root.success !== true) return { error: "API success=false" };
  if (!root.data || typeof root.data !== "object") return { error: "Missing data" };

  const data = root.data;
  if (!Array.isArray(data.modelScores)) return { error: "Missing modelScores" };
  if (data.modelScores.length > MAX_MODELS) return { error: "Too many models" };

  const historyMap = data.historyMap;
  const byName = new Map();
  const byId = new Map();

  for (const item of data.modelScores) {
    if (!item || typeof item !== "object") continue;
    const m = item;
    const name = typeof m.name === "string" ? m.name : null;
    const id = m.id != null ? String(m.id) : null;
    if (!name || !id) continue;
    const row = {
      id,
      name,
      metrics: normalizeMetrics(m, excludedMetrics),
      historyTail: extractHistoryTail(historyMap, id, historyBarCount),
    };
    byName.set(name, row);
    byId.set(id, row);
  }

  const sorted = [...byName.values()].sort(
    (a, b) => Number(b.metrics.score ?? 0) - Number(a.metrics.score ?? 0),
  );
  const rankByName = buildRankByName(sorted);

  return {
    top: sorted.slice(0, topCount),
    topCount,
    modelNames: sorted.map((r) => r.name),
    allModelNames: sorted.map((r) => r.name),
    rankByName,
    byName,
    byId,
    cachedAt: root.meta?.cachedAt,
  };
}

export function sortFavoritesByRank(rows) {
  return [...rows].sort((a, b) => {
    const ra = a.rank ?? Number.POSITIVE_INFINITY;
    const rb = b.rank ?? Number.POSITIVE_INFINITY;
    if (ra !== rb) return ra - rb;
    return String(a.name).localeCompare(String(b.name));
  });
}

export function resolveFavorites(fav, byName, rankByName) {
  const rows = [];
  const warnings = [];
  for (const f of fav.favorites) {
    const row = byName.get(f.name);
    const rank = rankByName?.get(f.name) ?? null;
    if (!row) {
      warnings.push(`Unknown model: ${f.name}`);
      rows.push({
        id: null,
        name: f.name,
        rank,
        metrics: {},
        historyTail: [],
        missing: true,
      });
      continue;
    }
    rows.push({ ...row, rank, missing: false });
  }
  return { rows: sortFavoritesByRank(rows), warnings };
}

export function filterMetricsForDisplay(metrics, excludedLabels, displayLabels = DEFAULT_METRICS) {
  const exclude = new Set(excludedLabels);
  const out = [];
  for (const label of displayLabels) {
    if (exclude.has(label)) continue;
    if (label in metrics) out.push([label, metrics[label]]);
  }
  return out;
}

export function localDateKey(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function mean(nums) {
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function clampInt(v, lo, hi) {
  const n = Math.floor(Number(v));
  if (!Number.isFinite(n)) return lo;
  return Math.min(hi, Math.max(lo, n));
}
