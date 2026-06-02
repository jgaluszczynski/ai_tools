export const TONE = {
  good: "#4ade80",
  neutral: "#f8fafc",
  bad: "#f87171",
  warning: "#f97316",
};

export const SCORE_COLORS = {
  brown: "#92400e",
  red: "#ef4444",
  orange: "#f97316",
  yellow: "#eab308",
  green: "#22c55e",
  magenta: "#e879f9",
};

export const BRAND = { green: "#4ade80", white: "#ffffff" };

function lerp(a, b, t) {
  const c = Math.max(0, Math.min(1, t));
  return Math.round(a + (b - a) * c);
}

function fixLerp(c1, c2, t) {
  const parse = (h) => [
    parseInt(h.slice(1, 3), 16),
    parseInt(h.slice(3, 5), 16),
    parseInt(h.slice(5, 7), 16),
  ];
  const [r1, g1, b1] = parse(c1);
  const [r2, g2, b2] = parse(c2);
  const c = Math.max(0, Math.min(1, t));
  return `rgb(${lerp(r1, r2, c)},${lerp(g1, g2, c)},${lerp(b1, b2, c)})`;
}

export function buildScoreScale(scores) {
  const nums = scores.filter((n) => typeof n === "number" && Number.isFinite(n));
  if (!nums.length) return { globalMax: 100, p80: 80 };
  const sorted = [...nums].sort((a, b) => a - b);
  const globalMax = sorted[sorted.length - 1];
  const p80 = sorted[Math.max(0, Math.floor(sorted.length * 0.8) - 1)] ?? globalMax;
  return { globalMax, p80 };
}

export function colorForScore(v, scale) {
  if (!Number.isFinite(v)) return TONE.neutral;
  const { globalMax, p80 } = scale;
  if (v >= globalMax) return SCORE_COLORS.magenta;
  if (globalMax > p80 && v >= p80) {
    const t = (v - p80) / (globalMax - p80);
    return fixLerp(SCORE_COLORS.yellow, SCORE_COLORS.green, t);
  }
  const denom = p80 > 0 ? p80 : globalMax || 1;
  const t = Math.max(0, Math.min(1, v / denom));
  if (t < 0.33) return fixLerp(SCORE_COLORS.brown, SCORE_COLORS.red, t / 0.33);
  if (t < 0.66) return fixLerp(SCORE_COLORS.red, SCORE_COLORS.orange, (t - 0.33) / 0.33);
  return fixLerp(SCORE_COLORS.orange, SCORE_COLORS.yellow, (t - 0.66) / 0.34);
}

export function formatDisplayValue(v) {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return String(v);
}

export function toneForMetric(label, value) {
  if (label === "status") {
    const s = String(value).toLowerCase();
    if (s === "good") return "good";
    if (s === "warning") return "warning";
    if (s === "unknown") return "neutral";
    return "bad";
  }
  if (label === "trend") {
    const s = String(value).toLowerCase();
    if (s === "up") return "good";
    if (s === "down") return "bad";
    return "neutral";
  }
  if (label === "is_stale") return value ? "bad" : "good";
  return "neutral";
}

export function valueColor(label, value, scoreScale) {
  if (label === "score" || label === "current_score") {
    return colorForScore(Number(value), scoreScale);
  }
  return TONE[toneForMetric(label, value)] || TONE.neutral;
}
