// together.js -- bring your own media, observe it together, talk about it.
//
// The browser decodes any image you drop (jpg/png/gif/webp) and converts it to PNG; the zero-dep
// world witnesses it as the glyph grid the model sees. Drag the seam to wipe between your photo and
// that witnessed sight -- the same frame, two ways of seeing. The chat is grounded in the sight,
// with a small memory the model carries across the conversation.

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let currentSight = null;
let pilotKind = "…";

function setStatus(note) {
  $("status").innerHTML = `pilot: <span class="pk">${esc(pilotKind)}</span> · ` +
    esc(note || "grounded in the witnessed sight · the model only knows what it can see");
}

// ---- bring your own image: decode anything in the browser, hand the world a PNG ----
async function fileToPng(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((res, rej) => {
      const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("decode failed")); i.src = url;
    });
    let w = img.naturalWidth, h = img.naturalHeight;
    const max = 640; if (w > max) { h = Math.round(h * max / w); w = max; }
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    c.getContext("2d").drawImage(img, 0, 0, w, h);
    const dataUrl = c.toDataURL("image/png");
    return { dataUrl, b64: dataUrl.split(",")[1], name: (file.name || "image").replace(/\.[^.]+$/, "") };
  } finally { URL.revokeObjectURL(url); }
}

async function addImage(file) {
  if (!file || !file.type.startsWith("image/")) { setStatus("that doesn't look like an image"); return; }
  setStatus("witnessing your image…");
  try {
    const { dataUrl, b64, name } = await fileToPng(file);
    const d = await (await fetch("./upload", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, png_b64: b64 }) })).json();
    if (d.error) { setStatus("upload: " + d.error); return; }
    currentSight = d.sight;
    showOverlay(dataUrl, d.sight);
    setStatus("witnessed -- drag the seam, then ask the model what it sees");
  } catch (e) { setStatus("couldn't read that image: " + e.message); }
}

function showOverlay(dataUrl, sight) {
  $("drop").style.display = "none";
  $("viewer").classList.add("on");
  $("wipe-row").hidden = false;
  $("ascii").textContent = (sight.ascii || []).join("\n");
  $("sight-meta").textContent =
    `the model's witnessed sight · ${sight.width}×${sight.height} · phash ${sight.phash} · ${sight.digest}`;
  const photo = $("photo");
  photo.onload = () => {
    $("viewer").style.aspectRatio = (photo.naturalWidth / photo.naturalHeight) || 1;
    fitAscii(sight);
    const cv = $("overlay");
    if (cv && window.drawContours) {
      cv.width = photo.clientWidth; cv.height = photo.clientHeight;
      const st = sight.structure || {};
      window.drawContours(cv.getContext("2d"), st.coords || [], cv.width, cv.height);
    }
  };
  if (window.renderColorMap) window.renderColorMap($("color-map"), sight.color);
  photo.src = dataUrl;
  setWipe($("wipe").value);
  const empty = $("chat-empty"); if (empty) empty.remove();
}

function fitAscii(sight) {
  const v = $("viewer"), a = $("ascii");
  const cols = ((sight.ascii && sight.ascii[0]) || "").length || 80;
  const rows = (sight.ascii && sight.ascii.length) || 1;
  a.style.fontSize = Math.max(4, v.clientWidth / cols / 0.6) + "px";  // mono char ~0.6em wide
  a.style.lineHeight = (v.clientHeight / rows) + "px";
}

function setWipe(v) {
  document.documentElement.style.setProperty("--wipe", v + "%");
}

// ---- the conversation, grounded + remembered ----
function addMsg(role, text) {
  const log = $("chat-log");
  const d = document.createElement("div");
  d.className = "msg " + (role === "assistant" ? "assistant" : "user");
  d.innerHTML = `<span class="who">${role === "assistant" ? "the model" : "you"}</span>${esc(text)}`;
  log.appendChild(d); log.scrollTop = log.scrollHeight;
}

async function send() {
  const inp = $("chat-input"), message = inp.value.trim();
  if (!message) return;
  inp.value = ""; addMsg("user", message);
  $("chat-send").disabled = true;
  setStatus("the model is looking…");
  try {
    const d = await (await fetch("./chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }) })).json();
    addMsg("assistant", d.error ? "(" + d.error + ")" : d.reply);
  } catch (e) { addMsg("assistant", "(couldn't reach the model: " + e.message + ")"); }
  finally { $("chat-send").disabled = false; setStatus(); $("chat-input").focus(); }
}

// ---- wiring ----
const drop = $("drop"), file = $("file");
drop.addEventListener("click", () => file.click());
drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } });
file.addEventListener("change", () => file.files[0] && addImage(file.files[0]));
["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => { const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) addImage(f); });
$("wipe").addEventListener("input", e => setWipe(e.target.value));
$("chat-send").addEventListener("click", send);
$("chat-input").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
window.addEventListener("resize", () => currentSight && fitAscii(currentSight));

(async function init() {
  try { pilotKind = (await (await fetch("./world")).json()).pilot || "none"; } catch (e) { /* offline */ }
  setStatus();
  try {
    const h = (await (await fetch("./chat")).json()).history || [];
    if (h.length) { const e = $("chat-empty"); if (e) e.remove(); h.forEach(m => addMsg(m.role, m.text)); }
  } catch (e) { /* no history */ }
})();
