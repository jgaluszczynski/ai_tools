/**
 * 1:1 port of har_utils/reduce_har.py for browser + Node parity tests.
 */

const DROP_HEADER_NAMES = new Set([
  ":authority",
  ":method",
  ":path",
  ":scheme",
  "accept-encoding",
  "accept-language",
  "connection",
  "content-length",
  "cookie",
  "host",
  "origin",
  "priority",
  "referer",
  "sec-ch-ua",
  "sec-ch-ua-mobile",
  "sec-ch-ua-platform",
  "sec-fetch-dest",
  "sec-fetch-mode",
  "sec-fetch-site",
  "sec-fetch-user",
  "set-cookie",
  "upgrade-insecure-requests",
  "user-agent",
]);

const SENSITIVE_HEADER_NAMES = new Set([
  "authorization",
  "proxy-authorization",
  "x-api-key",
  "x-auth-token",
  "x-csrf-token",
  "x-xsrf-token",
]);

const BINARY_MIME_PREFIXES = ["image/", "audio/", "video/", "font/"];

const BINARY_MIME_TYPES = new Set([
  "application/octet-stream",
  "application/pdf",
  "application/zip",
  "application/gzip",
  "application/x-gzip",
  "application/wasm",
]);

function headersToDict(headers, { redactSecrets }) {
  const out = {};
  for (const header of headers || []) {
    const name = header?.name;
    if (!name) continue;
    const key = name.toLowerCase();
    if (DROP_HEADER_NAMES.has(key) || key.startsWith("sec-ch-ua")) continue;
    let value = header.value ?? "";
    if (redactSecrets && SENSITIVE_HEADER_NAMES.has(key)) {
      value = "<redacted>";
    }
    out[key] = value;
  }
  return out;
}

function queryToDict(query) {
  const out = {};
  for (const item of query || []) {
    const name = item?.name;
    if (name == null) continue;
    out[String(name)] = String(item.value ?? "");
  }
  return out;
}

function urlWithoutQuery(url) {
  if (!url) return url;
  try {
    const parsed = new URL(url);
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return url;
  }
}

function looksBinary(mimeType, encoding) {
  if ((encoding || "").toLowerCase() === "base64") return true;
  const mime = (mimeType || "").split(";")[0].trim().toLowerCase();
  if (!mime) return false;
  if (BINARY_MIME_TYPES.has(mime)) return true;
  return BINARY_MIME_PREFIXES.some((prefix) => mime.startsWith(prefix));
}

function decodeBase64(text) {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(text, "base64").toString("utf-8");
  }
  return atob(text);
}

function decodeBodyText(text, encoding) {
  if (text == null) return null;
  if ((encoding || "").toLowerCase() !== "base64") return text;
  try {
    return decodeBase64(text);
  } catch {
    return null;
  }
}

function maybeParseJson(text, mimeType) {
  if (text == null) return null;
  const mime = (mimeType || "").toLowerCase();
  const looksJson = mime.includes("json") || text.startsWith("{") || text.startsWith("[");
  if (!looksJson) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function truncate(value, maxChars) {
  if (maxChars == null || typeof value !== "string") return value;
  if (value.length <= maxChars) return value;
  return `${value.slice(0, maxChars)}…<truncated ${value.length - maxChars} chars>`;
}

function reducePostData(postData, { maxBodyChars }) {
  if (!postData) return null;

  const mimeType = postData.mimeType;
  const text = postData.text;
  const params = postData.params;

  const reduced = {};
  if (mimeType) reduced.mimeType = mimeType;
  if (params) reduced.params = params;
  if (text != null) {
    reduced.body = truncate(maybeParseJson(text, mimeType), maxBodyChars);
  }
  return Object.keys(reduced).length ? reduced : null;
}

function reduceResponseContent(content, { maxBodyChars }) {
  if (!content) return null;

  const mimeType = content.mimeType;
  const encoding = content.encoding;
  const text = content.text;
  const size = content.size;

  const reduced = {};
  if (mimeType) reduced.mimeType = mimeType;
  if (size != null) reduced.size = size;

  if (text == null) return Object.keys(reduced).length ? reduced : null;

  if (looksBinary(mimeType, encoding)) {
    reduced.body_omitted = "binary_or_base64";
    return reduced;
  }

  const decoded = decodeBodyText(text, encoding);
  if (decoded == null) {
    reduced.body_omitted = "undecodable";
    return reduced;
  }

  reduced.body = truncate(maybeParseJson(decoded, mimeType), maxBodyChars);
  return reduced;
}

export function reduceEntry(entry, { redactSecrets = true, maxBodyChars = 20_000 } = {}) {
  const request = entry.request || {};
  const response = entry.response || {};

  const reducedRequest = {
    method: request.method,
    url: urlWithoutQuery(request.url),
  };
  const query = queryToDict(request.queryString);
  if (Object.keys(query).length) reducedRequest.query = query;

  const headers = headersToDict(request.headers, { redactSecrets });
  if (Object.keys(headers).length) reducedRequest.headers = headers;

  const postData = reducePostData(request.postData, { maxBodyChars });
  if (postData) reducedRequest.postData = postData;

  const reducedResponse = {
    status: response.status,
  };
  if (response.statusText) reducedResponse.statusText = response.statusText;

  const respHeaders = headersToDict(response.headers, { redactSecrets });
  if (Object.keys(respHeaders).length) reducedResponse.headers = respHeaders;

  const content = reduceResponseContent(response.content, { maxBodyChars });
  if (content) reducedResponse.content = content;

  return {
    startedDateTime: entry.startedDateTime,
    time_ms: entry.time,
    request: reducedRequest,
    response: reducedResponse,
  };
}

export function reduceHarFromObject(
  har,
  { source = "export.har", redactSecrets = true, maxBodyChars = 20_000 } = {},
) {
  const entries = har?.log?.entries;
  if (!Array.isArray(entries)) {
    throw new Error(`${source}: not a valid HAR (missing log.entries)`);
  }

  const reducedEntries = entries.map((entry) =>
    reduceEntry(entry, { redactSecrets, maxBodyChars }),
  );

  return {
    source,
    entry_count: reducedEntries.length,
    entries: reducedEntries,
  };
}
