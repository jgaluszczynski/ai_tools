import {
  DEFAULT_API_URL,
  MAX_BODY_BYTES,
  FETCH_TIMEOUT_MS,
  REFRESH_ALARM_MINUTES,
  DEFAULT_TOP_COUNT,
  MODELS_API_URL,
} from "./labels.js";
import {
  parseDashboard,
  parseFavoriteNames,
  resolveFavorites,
  localDateKey,
  migrateFavoritesText,
  namesFromApiModels,
  mergeModelNameLists,
  rankByNameToObject,
} from "./parse.js";

const SYNC_KEYS = [
  "favoriteModels",
  "favoritesText",
  "excludedMetrics",
  "historyBarCount",
  "topCount",
];

export async function getConfig() {
  const sync = await chrome.storage.sync.get(SYNC_KEYS);
  const excludedRaw = sync.excludedMetrics || "";
  const excludedMetrics =
    typeof excludedRaw === "string"
      ? excludedRaw.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
      : Array.isArray(excludedRaw)
        ? excludedRaw
        : [];

  let favoriteModels = Array.isArray(sync.favoriteModels) ? sync.favoriteModels : [];
  if (!favoriteModels.length && sync.favoritesText) {
    favoriteModels = migrateFavoritesText(sync.favoritesText);
  }

  return {
    favoriteModels,
    excludedMetrics,
    apiUrl: DEFAULT_API_URL,
    historyBarCount: Number(sync.historyBarCount) || 7,
    topCount: Number(sync.topCount) || DEFAULT_TOP_COUNT,
  };
}

function rowSnapshot(row) {
  return {
    id: row.id,
    name: row.name,
    rank: row.rank ?? null,
    metrics: { ...row.metrics },
    history_tail: [...(row.historyTail || [])],
  };
}


async function fetchModelCatalog() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(MODELS_API_URL, { signal: controller.signal, credentials: "omit" });
    if (!res.ok) return [];
    return namesFromApiModels(await res.json());
  } finally {
    clearTimeout(timer);
  }
}

function buildLatestPayload(parsed, favoritesRows, catalogNames) {
  return {
    fetchedAt: new Date().toISOString(),
    cachedAt: parsed.cachedAt || null,
    topCount: parsed.topCount,
    modelNames: parsed.modelNames,
    allModelNames: mergeModelNameLists(parsed.modelNames, catalogNames),
    rankByName: rankByNameToObject(parsed.rankByName),
    top: parsed.top.map(rowSnapshot),
    favorites: favoritesRows.map((r) => rowSnapshot(r)),
    top_ids: parsed.top.map((r) => r.id),
    top5: parsed.top.map(rowSnapshot),
    top5_ids: parsed.top.map((r) => r.id),
  };
}

export async function fetchAndStore() {
  const config = await getConfig();
  const url = config.apiUrl;
  if (!url.startsWith("https://aistupidlevel.info/")) {
    throw new Error("API URL must be https://aistupidlevel.info/");
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, { signal: controller.signal, credentials: "omit" });
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const cl = res.headers.get("content-length");
  if (cl && Number(cl) > MAX_BODY_BYTES) throw new Error("Response too large");

  const text = await res.text();
  if (text.length > MAX_BODY_BYTES) throw new Error("Body too large");

  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error("Invalid JSON");
  }

  const catalogNames = await fetchModelCatalog().catch(() => []);

  const parsed = parseDashboard(raw, {
    historyBarCount: config.historyBarCount,
    excludedMetrics: config.excludedMetrics,
    topCount: config.topCount,
  });
  if (parsed.error) throw new Error(parsed.error);

  const fav = parseFavoriteNames(config.favoriteModels);
  const { rows: favoritesRows } = resolveFavorites(fav, parsed.byName, parsed.rankByName);
  const latest = buildLatestPayload(parsed, favoritesRows, catalogNames);

  const dateKey = localDateKey();
  const stored = await chrome.storage.local.get(["snapshots"]);
  const snapshots = stored.snapshots || {};
  if (!snapshots[dateKey]) snapshots[dateKey] = latest;

  await chrome.storage.local.set({
    latest,
    snapshots,
    lastError: null,
    lastFetchAt: latest.fetchedAt,
  });

  chrome.runtime.sendMessage({ type: "UPDATED" }).catch(() => {});
  return latest;
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("refresh", { periodInMinutes: REFRESH_ALARM_MINUTES });
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  fetchAndStore().catch((e) => storeError(e));
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "refresh") fetchAndStore().catch((e) => storeError(e));
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "REFRESH") {
    fetchAndStore()
      .then((latest) => sendResponse({ ok: true, latest }))
      .catch((e) => {
        storeError(e);
        sendResponse({ ok: false, error: String(e.message || e) });
      });
    return true;
  }
  if (msg?.type === "GET_LATEST") {
    chrome.storage.local.get(["latest", "snapshots", "lastError", "lastFetchAt"]).then((data) => {
      sendResponse({ ok: true, ...data });
    });
    return true;
  }
});

async function storeError(e) {
  await chrome.storage.local.set({
    lastError: String(e?.message || e),
    lastFetchAt: new Date().toISOString(),
  });
  chrome.runtime.sendMessage({ type: "UPDATED" }).catch(() => {});
}
