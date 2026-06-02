import { buildScoreScale, colorForScore } from "./colors.js";

const MIN_H = 2;
const MAX_H = 20;

export function renderSparkline(container, scores) {
  while (container.firstChild) container.removeChild(container.firstChild);
  if (!scores.length) {
    const empty = document.createElement("span");
    empty.className = "sparkline-empty";
    empty.textContent = "—";
    container.appendChild(empty);
    return;
  }

  const lo = Math.min(...scores);
  const hi = Math.max(...scores);
  const scale = buildScoreScale(scores);
  const wrap = document.createElement("div");
  wrap.className = "sparkline-bars";
  wrap.setAttribute("role", "img");
  wrap.title = `history=[${scores.join(", ")}]`;

  for (const s of scores) {
    const h = hi > lo ? ((s - lo) / (hi - lo)) * (MAX_H - MIN_H) + MIN_H : MAX_H;
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = `${h}px`;
    const col = colorForScore(s, scale);
    bar.style.background = col;
    bar.style.boxShadow = `0 0 3px color-mix(in srgb, ${col} 55%, transparent)`;
    wrap.appendChild(bar);
  }

  container.appendChild(wrap);
}
