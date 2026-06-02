# [ maitrix ]

Chrome MV3 side panel for live [aistupidlevel.info](https://aistupidlevel.info) benchmark data.

## Install

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select the `AI_bench` folder
4. Click the extension icon → **Open side panel**

## Panel

Chrome shows `[ maitrix ]` in the native side panel toolbar (not hideable). Inside the panel:

- **Header** — last fetch time + ⚙ **Settings** (opens options)
- **TOP N** — models ranked by combined score (N = 3–10, configurable)
  - `#rank`, name, history sparkline (right), `modelScores` metric chips
  - List position `#1` → **magenta** name; other favorites in this list → **purple**
- **My fav** — your chosen models, sorted by live API rank
  - `#rank` + name on one line; sparkline below (left), bordered box
  - `#1` globally → magenta name; other favorites → purple
- **Footer** — day-over-day variance when prior snapshots exist

Open the panel → shows cached data, then fetches fresh data. Background refresh every **30 minutes**.

## Options (⚙ or extension Options)

| Setting | Description |
|--------|-------------|
| **TOP models to show** | 3–10 (default 5) |
| **My fav** | Dropdown of **all** catalog models as `model-name (#rank)`, A–Z + **Add**; remove with × on tags |
| **Excluded metrics** | `snake_case` labels to hide (one per line). **Defaults on first install:** `current_score`, `confidence_lower`, `confidence_upper`, `is_stale`, `standard_error`, `uses_reasoning_effort` |
| **History bars** | Sparkline length, 5–24 (default 7) |

**Save** stores settings. **Save & refresh** also fetches the dashboard immediately.

## Metric chips (Python-style)

From `modelScores`, e.g. `score=65`, `status=warning`, `is_stale=False` (no quotes on strings; values **bold**).

Default chips: `score`, `current_score`, `standard_error`, `confidence_lower`, `confidence_upper`, `status`, `trend`, `is_stale`, `uses_reasoning_effort`

Extend in [`src/labels.js`](src/labels.js) (`MODEL_SCORE_LABELS`, `DEFAULT_METRICS`).

## Colors

| Kind | Color |
|------|--------|
| `status=good`, `trend=up`, `is_stale=False` | Green |
| `status=warning` | Orange |
| Neutral / `trend=stable` | White |
| Bad / `trend=down`, stale | Red |
| `score` / `current_score` | Brown → red → orange → yellow → green (top 20% of view); highest in view → magenta |
| Sparkline bars | Same score gradient |
| Favorite names | Purple; **#1** (list position in TOP N, or global rank in My fav) → magenta |

## Data & refresh

- **Source:** `https://aistupidlevel.info/dashboard/cached?period=latest&sortBy=combined&analyticsPeriod=latest` (fixed; not user-configurable)
- **Model list:** dashboard + `/api/models` merged for the favorites dropdown
- **`latest`** — updated on every successful fetch (panel open, 30 min alarm, Save & refresh)
- **Daily snapshot** — first successful fetch per **local calendar day** (not overwritten same day); used for footer variance

## Security

- `textContent` / `createElement` only (no `innerHTML`)
- JSON cap 2 MB, 10 s fetch timeout
