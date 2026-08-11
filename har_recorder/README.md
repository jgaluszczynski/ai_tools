# HarRecorder

Chrome DevTools extension that records **XHR/fetch** requests between **Start** and **Stop**, filters them Network-panel-style, shows session stats, and downloads:

- **Reduced JSON** — same shape as [`har_utils/reduce_har.py`](../har_utils/reduce_har.py) output
- **Raw HAR** — standard `log.entries` HAR for other tools (unredacted)

## Install (unpacked)

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select this `har_recorder/` folder

## Usage

1. Open DevTools on the tab you want to capture (**DevTools must stay open** while recording).
2. Open the **HarRecorder** panel.
3. Click **Start** (clears any previous buffer), perform the flow, then **Stop**.
4. Optionally set filters:
   - **Domain filter** — hostname substring (case-insensitive)
   - **URL filters** — space-separated tokens; plain token = include, `-token` = exclude (same idea as the Network panel)
5. Click **Download reduced JSON** (primary) or **Download raw HAR**.

### Copy DevTools filter

Chrome does not expose an API to open the built-in Network panel with filters pre-applied. **Copy DevTools filter** builds an equivalent filter string (e.g. `domain:*api.example.com* token -exclude`) and copies it to the clipboard — paste it into the Network panel filter box manually.

## Reduce options

- **Redact secrets** (default on) — masks sensitive **headers**, **query params**, and **JSON/form field names** (Authorization, API keys, `password`, `access_token`, etc.)
- **Max body chars** (default 20000) — truncates long string bodies; `0` = no limit

Raw HAR export is never redacted; the UI confirms before download.

## Parity / source of truth

[`har_utils/reduce_har.py`](../har_utils/reduce_har.py) is the source of truth for reduction logic. [`reduce.js`](reduce.js) is a 1:1 port — after changing either file, re-run:

```bash
make test
# or: node har_recorder/test/parity_test.mjs
```

Compares `reduce.js` output with `poetry run python har_utils/reduce_har.py` on the same fixture HAR.

## Limitations

- Records only `xhr` and `fetch` resource types (DevTools “Fetch/XHR”).
- Requires DevTools to be open during capture (`chrome.devtools.network` API).
- Network panel navigation / filter application is clipboard handoff only.
- Redaction is name-based (known field/header names), not a full secret scanner.
