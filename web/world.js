// world.js -- the shared world, live in the browser.
//
// Subscribes to the body's loop over SSE: every proposed action streams in as a witnessed step
// (gate decision, the hands acting, the receipt) and the world's new state (material + journal).
// The operator can propose actions too. The receipt is re-checked CLIENT-SIDE (recheck.js) -- the
// meet re-derived from the certificate's own evidence. Trust nothing; check it.
import { recheckComposed } from "./recheck.js";

const $ = id => document.getElementById(id);
let liveCert = null;

const announce = msg => { $("status").textContent = msg; };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const shortDigest = d => !d ? "--" : (d.length > 30 ? d.slice(0, 30) + "…" : d);

function renderWorld(snap) {
  $("world-root").textContent = "root: " + snap.root;
  $("files").innerHTML = (snap.files || []).map(f => {
    const focus = snap.focus && f.name === snap.focus.name;
    return `<li class="${focus ? "focus" : ""}"><span>${esc(f.name)}${focus ? " ◂" : ""}</span><span>${f.size} B</span></li>`;
  }).join("") || "<li>(the world is empty)</li>";
  if (snap.focus) {
    $("focus-name").textContent = "▸ " + snap.focus.name;
    $("focus-content").textContent = snap.focus.content || "(empty file)";
  }
  renderJournal(snap.journal || []);
}

function renderJournal(journal) {
  $("journal").innerHTML = journal.map(e => {
    const v = (e.detail && e.detail.certificate && e.detail.certificate.verdict) || "";
    return `<div class="je"><span class="jk">${esc(e.kind)}</span><span>${esc(e.summary || "")}</span>` +
      `<span class="jt">${v ? `<span class="tag ${esc(v)}">${esc(v)}</span>` : ""}</span></div>`;
  }).join("");
  const j = $("journal"); j.scrollTop = j.scrollHeight;
}

function renderCertificate(cert) {
  liveCert = cert || null;
  $("recheck-out").hidden = true;
  if (!cert) return;
  $("cert-claim").textContent = cert.claim || "--";
  const v = $("cert-verdict"); v.textContent = cert.verdict || "--"; v.className = "tag " + (cert.verdict || "unverifiable");
  $("cert-oracle").textContent = cert.oracle || "--";
  $("cert-evidence").innerHTML = (cert.evidence || []).map(([k, val]) =>
    `<div class="ev"><span class="ek">${esc(k)}</span><span class="evv"><span class="tag ${esc(val)}">${esc(val)}</span></span></div>`).join("");
}

function renderMove(step) {
  const dec = $("move-decision");
  dec.textContent = step.decision || "--";
  dec.className = "tag " + (step.decision === "allow" ? "verified" : step.decision === "deny" ? "refuted" : "needs-human");
  $("move-flags").innerHTML =
    `<span class="flag ${step.acted ? "on" : "off"}">${step.acted ? "acted" : "did not act"}</span>` +
    `<span class="flag ${step.verified ? "on" : "off"}">${step.verified ? "verified its work" : "unverified"}</span>` +
    (step.rolled_back ? `<span class="flag off">rolled back</span>` : "");
  $("digest-before").innerHTML = `<b>saw before</b> ${esc(shortDigest(step.before_digest))}`;
  $("digest-after").innerHTML = `<b>saw after</b> ${esc(shortDigest(step.after_digest))}`;
  $("move-reasons").innerHTML = (step.reasons || []).map(r => `<li>${esc(r)}</li>`).join("");
  renderCertificate(step.certificate);
}

function recheck() {
  if (!liveCert) return;
  const r = recheckComposed(liveCert);
  const out = $("recheck-out"); out.hidden = false;
  out.innerHTML =
    `<div class="rc-line">re-derived in your browser -- the meet of [` +
    r.subs.map(s => `<span class="tag ${esc(s.verdict)}">${esc(s.verdict)}</span>`).join(" · ") +
    `] → <span class="tag ${esc(r.verdict)}">${esc(r.verdict)}</span></div>` +
    `<div class="rc-match ${r.matches ? "ok" : "bad"}">` +
    (r.matches ? "✓ reproduces the receipt -- you didn't have to trust it"
               : "✗ does not match the receipt") + `</div>`;
  announce(`Re-checked: the meet reproduces ${r.verdict}, ${r.matches ? "matches" : "does not match"} the receipt.`);
}

async function propose() {
  const body = {
    kind: "fs.write",
    target: $("act-target").value.trim(),
    content: $("act-content").value,
    justification: $("act-justification").value.trim(),
  };
  $("act-btn").disabled = true;
  try {
    const r = await fetch("./act", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const step = await r.json();
    if (step.error) { announce("error: " + step.error); return; }
    renderMove(step);
    announce(`Proposed ${body.kind} ${body.target}: gate ${step.decision}, ` +
      `${step.acted ? "acted" : "no action"}, receipt ${step.certificate.verdict}.`);
  } catch (e) {
    announce("request failed: " + e.message);
  } finally {
    $("act-btn").disabled = false;
  }
}

// ---- autopilot: a model drives the body, the surface keeps it honest ----
let apStep = 0;

function setRunning(running) {
  $("ap-run").disabled = running;
  $("ap-stop").disabled = !running;
}

// each autonomous step's reasoning is the mind's voice -- shown beside the verdict the surface gave it
function appendVoice(step) {
  if (!step.reasoning) return;
  apStep += 1;
  $("transcript").hidden = false;
  const v = step.certificate ? step.certificate.verdict : "";
  const target = (step.target || "").split(/[\\/]/).pop();
  const div = document.createElement("div");
  div.className = "voice";
  div.innerHTML = `<span class="vi">${apStep}</span>` +
    `<span class="vt">${esc(step.reasoning)} <em>-- ${esc(step.kind)} ${esc(target)}</em></span>` +
    `<span class="vv"><span class="tag ${esc(v)}">${esc(v)}</span></span>`;
  $("transcript").appendChild(div);
  $("transcript").scrollTop = $("transcript").scrollHeight;
}

async function runAutopilot() {
  apStep = 0; $("transcript").innerHTML = ""; $("transcript").hidden = false;
  setRunning(true);
  try {
    const r = await fetch("./autopilot", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: $("ap-goal").value.trim(), max_steps: parseInt($("ap-steps").value) || 4 }),
    });
    const d = await r.json();
    if (d.error) { announce("autopilot: " + d.error); setRunning(false); return; }
    announce(`Autopilot running (${d.pilot}) toward: ${$("ap-goal").value.trim()}`);
  } catch (e) {
    announce("autopilot failed: " + e.message); setRunning(false);
  }
}

async function stopAutopilot() {
  try { await fetch("./autopilot/stop", { method: "POST" }); } catch (e) { /* ignore */ }
  announce("Autopilot stop requested.");
}

async function initPilot() {
  try {
    const d = await (await fetch("./world")).json();
    $("pilot-kind").textContent = d.pilot || "none";
    setRunning(!!d.running);
  } catch (e) { /* the stream will still drive the view */ }
}

function connect() {
  const es = new EventSource("./world/stream");
  es.addEventListener("world", e => renderWorld(JSON.parse(e.data)));
  es.addEventListener("step", e => { const s = JSON.parse(e.data); renderMove(s); appendVoice(s); });
  es.addEventListener("autopilot", () => { setRunning(false); announce("Autopilot finished."); });
  es.onerror = () => announce("stream disconnected -- retrying…");
}

$("act-btn").addEventListener("click", propose);
$("recheck-btn").addEventListener("click", recheck);
$("ap-run").addEventListener("click", runAutopilot);
$("ap-stop").addEventListener("click", stopAutopilot);
initPilot();
connect();
