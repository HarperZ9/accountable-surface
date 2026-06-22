// watch.js — the broadcast. Read-only: a spectator tunes into the shared world and sees what the
// operator and the model see — the witnessed material (including the glyph grid the model actually
// perceives), the mind's voice, and every gated, witnessed move — streamed live. Like a stream.

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function setLive(on, label) {
  $("live").className = "live" + (on ? " on" : "");
  $("live-label").textContent = label || (on ? "live" : "idle");
}

function setNow(goal) {
  $("now").innerHTML = goal ? `now: ${esc(goal)}` : "<b>idle — waiting for a goal</b>";
}

// ---- the ASCII video player: moving material, played a witnessed frame at a time ----
let reel = null, reelIdx = 0, reelTimer = null;

function renderReelFrame() {
  const f = reel.frames[reelIdx];
  $("screen").innerHTML = `<pre class="sight">${esc(f.ascii.join("\n"))}</pre>`;
  $("stage-cap").innerHTML = `the stage &middot; <b>moving material</b> &middot; ▶ frame ${reelIdx + 1}/${reel.count}`;
  $("sightmeta").textContent = `${f.width}×${f.height} · phash ${f.phash} · ${reel.fps} fps · each frame witnessed`;
}

function playReel(r) {
  if (reelTimer) clearInterval(reelTimer);
  reel = r;
  if (!reel || !reel.count) { reelTimer = null; return; }
  reelIdx = 0;
  renderReelFrame();
  reelTimer = setInterval(() => { reelIdx = (reelIdx + 1) % reel.count; renderReelFrame(); }, 1000 / (reel.fps || 8));
}

function renderStage(snap) {
  if (reelTimer) return;   // a reel is playing — it owns the stage (moving material is the headline)
  const screen = $("screen");
  const sights = snap.sights || [];
  if (sights.length) {                              // show what the model sees — the witnessed grid
    const s = sights[0];
    screen.innerHTML = `<pre class="sight">${esc(s.ascii.join("\n"))}</pre>`;
    $("stage-cap").innerHTML = `the stage &middot; <b>what the model sees</b> &middot; ${esc(s.name)}`;
    $("sightmeta").textContent = `${s.width}×${s.height} · phash ${s.phash} · ${s.digest}`;
    return;
  }
  const focus = snap.focus;
  if (focus && focus.content !== undefined) {
    screen.innerHTML = `<pre class="text">${esc(focus.content)}</pre>` ||
      `<span class="empty">(empty file)</span>`;
    $("stage-cap").innerHTML = `the stage &middot; <b>in focus</b> &middot; ${esc(focus.name)}`;
    $("sightmeta").textContent = "";
    return;
  }
  screen.innerHTML = `<span class="empty">the world is quiet — ${(snap.files || []).length} file(s)</span>`;
  $("sightmeta").textContent = "";
}

let moveN = 0;
function addVoice(step) {
  if (!step.reasoning) return;
  moveN += 1;
  const target = (step.target || "").split(/[\\/]/).pop();
  const div = document.createElement("div");
  div.className = "vline";
  div.innerHTML = `<span class="who">the model · move ${moveN}</span>${esc(step.reasoning)} ` +
    `<em>— ${esc(step.kind)} ${esc(target)}</em>`;
  $("voice").appendChild(div);
  $("voice").scrollTop = $("voice").scrollHeight;
}

function addTick(step) {
  const target = (step.target || "").split(/[\\/]/).pop();
  const v = step.certificate ? step.certificate.verdict : "";
  const div = document.createElement("div");
  div.className = "tick";
  div.innerHTML = `<span class="gate"><span class="tag ${esc(step.decision)}">${esc(step.decision)}</span></span>` +
    `<span>${esc(step.kind)} ${esc(target)}</span>` +
    `<span><span class="tag ${esc(v)}">${esc(v)}</span></span>`;
  $("ticker").appendChild(div);
  $("ticker").scrollTop = $("ticker").scrollHeight;
}

async function init() {
  try {
    const d = await (await fetch("./world")).json();
    $("pilot").textContent = d.pilot || "none";
    setNow(d.goal); setLive(!!d.running, d.running ? "live" : "idle");
    renderStage(d);
  } catch (e) { /* the stream will drive the view */ }
  try {
    const rl = await (await fetch("./reel")).json();
    if (rl && rl.count) playReel(rl);   // moving material present — start the ASCII video player
  } catch (e) { /* no reel */ }
}

function connect() {
  const es = new EventSource("./world/stream");
  es.addEventListener("world", e => renderStage(JSON.parse(e.data)));
  es.addEventListener("step", e => { const s = JSON.parse(e.data); addVoice(s); addTick(s); });
  es.addEventListener("status", e => {
    const d = JSON.parse(e.data); setNow(d.goal); setLive(true, "live");
    if (d.pilot) $("pilot").textContent = d.pilot;
  });
  es.addEventListener("autopilot", () => setLive(false, "idle"));
  es.onerror = () => setLive(false, "reconnecting");
}

init();
connect();
