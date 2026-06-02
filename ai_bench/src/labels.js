/** API camelCase → Python-style snake_case labels for modelScores chips. */
export const MODEL_SCORE_LABELS = {
  score: "score",
  currentScore: "current_score",
  standardError: "standard_error",
  confidenceLower: "confidence_lower",
  confidenceUpper: "confidence_upper",
  status: "status",
  trend: "trend",
  isStale: "is_stale",
  usesReasoningEffort: "uses_reasoning_effort",
  isNew: "is_new",
  provider: "provider",
  vendor: "vendor",
  lastUpdated: "last_updated",
  id: "id",
};

export const DEFAULT_METRICS = [
  "score",
  "current_score",
  "standard_error",
  "confidence_lower",
  "confidence_upper",
  "status",
  "trend",
  "is_stale",
  "uses_reasoning_effort",
];

export const DEFAULT_API_URL =
  "https://aistupidlevel.info/dashboard/cached?period=latest&sortBy=combined&analyticsPeriod=latest";

export const MAX_BODY_BYTES = 2 * 1024 * 1024;
export const FETCH_TIMEOUT_MS = 10_000;
export const REFRESH_ALARM_MINUTES = 30;
export const MAX_MODELS = 50;
export const MAX_FAVORITES = 12;
export const MIN_TOP_COUNT = 3;
export const MAX_TOP_COUNT = 10;
export const DEFAULT_TOP_COUNT = 5;
export const MAX_NAME_LEN = 80;
export const MODELS_API_URL = "https://aistupidlevel.info/api/models";
