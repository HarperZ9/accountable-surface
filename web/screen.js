// screen.js -- watch the live witnessed screen: the model and you see the same frame.
//
// Per ("capture", {frame_index, sight}) SSE event we render the witnessed sight the
// model reads -- ascii shape + structure contours (overlay.js) + OKLab colour map.
// No raw screen pixels cross the wire; the witnessed sight is the shared medium.

const $ = id => document.getElementById(id);

function render(sight) {
  $("ascii").textContent = (sight.ascii || []).join("\n");
  const cv = $("overlay"), pre = $("ascii");
  cv.width = pre.clientWidth || 320; cv.height = pre.clientHeight || 240;
  if (window.drawContours) window.drawContours(cv.getContext("2d"),
    (sight.structure && sight.structure.coords) || [], cv.width, cv.height);
  if (window.renderColorMap) window.renderColorMap($("color-map"), sight.color);
  $("meta").textContent = `${sight.width}×${sight.height} · phash ${sight.phash} · ` +
    `${(sight.structure && sight.structure.contours) || 0} contours · ${sight.digest}`;
}

const es = new EventSource("/world/stream");
es.addEventListener("capture", e => {
  const d = JSON.parse(e.data);
  if (d.error) { $("status").textContent = "refused: " + d.error; return; }
  if (d.started) { $("status").textContent = "capturing · region " + JSON.stringify(d.region); return; }
  if (d.receipt) { $("status").textContent = `stopped · ${d.receipt.frames} frames witnessed`; return; }
  if (d.sight) render(d.sight);
});

function region() {
  const v = id => parseInt($(id).value, 10);
  const r = [v("x"), v("y"), v("w"), v("h")];
  return r.every(n => Number.isFinite(n)) ? r : null;
}
$("start").addEventListener("click", async () => {
  const res = await (await fetch("/capture/start", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ region: region() }) })).json();
  $("status").textContent = res.error ? "refused: " + res.error : "starting…";
});
$("stop").addEventListener("click", () => fetch("/capture/stop", { method: "POST" }));
