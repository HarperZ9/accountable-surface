// overlay.js — draw the witnessed structure + colour on the spectator's canvas.
//
// The model reads sight.structure.coords (polylines normalized to [0,1]) and
// sight.color.map (legend letters). Here the spectator sees the SAME data drawn
// over the same photo — one frame, two ways of seeing. Pure coord math is
// exported for a node test; the browser also gets these on `window`.

// Map normalized [0,1] polylines to pixel coords for a w×h canvas. Pure.
export function normToCanvas(coords, w, h) {
  return coords.map(path => path.map(([x, y]) => [x * w, y * h]));
}

// Stroke the witnessed contours on a 2D context sized w×h.
export function drawContours(ctx, coords, w, h, opts = {}) {
  const paths = normToCanvas(coords, w, h);
  ctx.clearRect(0, 0, w, h);
  ctx.lineWidth = opts.lineWidth || 1.5;
  ctx.strokeStyle = opts.stroke || "rgba(255,80,0,0.9)";
  ctx.lineJoin = "round";
  for (const path of paths) {
    if (path.length < 2) continue;
    ctx.beginPath();
    ctx.moveTo(path[0][0], path[0][1]);
    for (let i = 1; i < path.length; i++) ctx.lineTo(path[i][0], path[i][1]);
    ctx.stroke();
  }
}

// Legend letter -> a representative css colour (mirrors sight.py _LEGEND).
export const LETTER_CSS = {
  k: "#111", w: "#eee", n: "#888", r: "#d23", o: "#e72",
  y: "#dd3", g: "#2b6", c: "#2bd", b: "#36d", m: "#a3c",
};

// Render the spatial colour map (rows of legend letters) into a container as a grid of swatches.
export function renderColorMap(container, color) {
  if (!container) return;
  const map = (color && color.map) || [];
  container.style.display = "grid";
  container.style.gridTemplateColumns = `repeat(${(map[0] || "").length || 1}, 1fr)`;
  container.innerHTML = map.flatMap(row =>
    [...row].map(ch => `<span style="background:${LETTER_CSS[ch] || "#000"}" title="${ch}"></span>`)
  ).join("");
}

if (typeof window !== "undefined") {
  window.normToCanvas = normToCanvas;
  window.drawContours = drawContours;
  window.renderColorMap = renderColorMap;
}
