import {
  MIN_TOP_COUNT,
  MAX_TOP_COUNT,
  DEFAULT_TOP_COUNT,
  MAX_FAVORITES,
  DEFAULT_EXCLUDED_METRICS,
  parseExcludedMetrics,
  formatExcludedMetricsForStorage,
} from "./labels.js";

const KEYS = ["favoriteModels", "excludedMetrics", "historyBarCount", "topCount"];

let favoriteModels = [];
let allModelNames = [];
let rankByName = {};

function fillTopCountSelect(selected) {
  const sel = document.getElementById("topCount");
  sel.replaceChildren();
  for (let n = MIN_TOP_COUNT; n <= MAX_TOP_COUNT; n++) {
    const opt = document.createElement("option");
    opt.value = String(n);
    opt.textContent = String(n);
    if (n === selected) opt.selected = true;
    sel.appendChild(opt);
  }
}

function fillModelPick(names) {
  if (names.length) allModelNames = names;
  const sel = document.getElementById("modelPick");
  sel.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = names.length ? "Select model…" : "— refresh to load models —";
  sel.appendChild(placeholder);
  const chosen = new Set(favoriteModels);
  const list = [...(names.length ? names : allModelNames)].sort((a, b) =>
    a.localeCompare(b),
  );
  for (const name of list) {
    const opt = document.createElement("option");
    opt.value = name;
    const rank = rankByName[name];
    opt.textContent = rank != null ? `${name} (#${rank})` : name;
    if (chosen.has(name)) {
      opt.disabled = true;
      opt.textContent += " ✓";
    }
    sel.appendChild(opt);
  }
}

function renderFavList() {
  const list = document.getElementById("favList");
  list.replaceChildren();
  for (const name of favoriteModels) {
    const tag = document.createElement("span");
    tag.className = "fav-tag";
    const label = document.createElement("span");
    label.textContent = name;
    tag.appendChild(label);
    const rm = document.createElement("button");
    rm.type = "button";
    rm.setAttribute("aria-label", `Remove ${name}`);
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      favoriteModels = favoriteModels.filter((n) => n !== name);
      renderFavList();
      fillModelPick(allModelNames);
    });
    tag.appendChild(rm);
    list.appendChild(tag);
  }
}

async function loadModels() {
  const res = await chrome.runtime.sendMessage({ type: "GET_LATEST" });
  let latest = res?.latest;
  let names = latest?.allModelNames || latest?.modelNames;
  rankByName = latest?.rankByName || {};
  if (!names?.length) {
    const refresh = await chrome.runtime.sendMessage({ type: "REFRESH" });
    latest = refresh?.latest;
    names = latest?.allModelNames || latest?.modelNames || [];
    rankByName = latest?.rankByName || {};
  }
  allModelNames = names;
  fillModelPick(allModelNames);
  return names;
}

function renderBrand() {
  const el = document.getElementById("optBrand");
  if (!el) return;
  el.replaceChildren();
  const mk = (t, white) => {
    const s = document.createElement("span");
    s.style.color = white ? "#fff" : "#16a34a";
    s.style.fontWeight = "700";
    s.textContent = t;
    return s;
  };
  el.appendChild(mk("[ ", false));
  el.appendChild(mk("m", false));
  el.appendChild(mk("ai", true));
  el.appendChild(mk("trix", false));
  el.appendChild(mk(" ]", false));
}

async function load() {
  renderBrand();
  const data = await chrome.storage.sync.get([...KEYS, "favoritesText"]);
  if (Array.isArray(data.favoriteModels)) {
    favoriteModels = [...data.favoriteModels];
  } else if (data.favoritesText) {
    favoriteModels = data.favoritesText
      .split("\n")
      .map((l) => l.replace(/^#\d+\s*/, "").trim())
      .filter(Boolean);
  }
  fillTopCountSelect(Number(data.topCount) || DEFAULT_TOP_COUNT);
  const excluded = parseExcludedMetrics(data.excludedMetrics);
  document.getElementById("excluded").value =
    data.excludedMetrics === undefined
      ? formatExcludedMetricsForStorage(DEFAULT_EXCLUDED_METRICS)
      : formatExcludedMetricsForStorage(excluded);
  document.getElementById("historyBarCount").value = data.historyBarCount || 7;
  renderFavList();
  await loadModels();
}

async function save(refresh) {
  const status = document.getElementById("status");
  const excludedMetrics = document.getElementById("excluded").value.trim();
  let historyBarCount = Number(document.getElementById("historyBarCount").value);
  const topCount = Number(document.getElementById("topCount").value) || DEFAULT_TOP_COUNT;
  if (!Number.isFinite(historyBarCount)) historyBarCount = 7;
  historyBarCount = Math.min(24, Math.max(5, Math.floor(historyBarCount)));

  await chrome.storage.sync.set({
    favoriteModels: favoriteModels.slice(0, MAX_FAVORITES),
    excludedMetrics,
    historyBarCount,
    topCount,
  });
  status.textContent = "Saved.";

  if (refresh) {
    status.textContent = "Saved. Refreshing…";
    const res = await chrome.runtime.sendMessage({ type: "REFRESH" });
    status.textContent = res?.ok ? "Saved and refreshed." : `Refresh failed: ${res?.error}`;
    if (res?.ok) await loadModels();
  }
}

document.getElementById("addFav").addEventListener("click", () => {
  const sel = document.getElementById("modelPick");
  const name = sel.value;
  if (!name || favoriteModels.includes(name)) return;
  if (favoriteModels.length >= MAX_FAVORITES) {
    document.getElementById("status").textContent = `Max ${MAX_FAVORITES} favorites.`;
    return;
  }
  favoriteModels.push(name);
  renderFavList();
  sel.value = "";
  const names = [...sel.options].map((o) => o.value).filter(Boolean);
  fillModelPick(allModelNames);
});

document.getElementById("save").addEventListener("click", () => save(false));
document.getElementById("refresh").addEventListener("click", () => save(true));
load();
