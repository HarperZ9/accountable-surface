// The world server's per-run token. The server prints a URL carrying ?token=...; this tab
// keeps it in sessionStorage, strips it from the address bar, and sends it on every API call.
// EventSource cannot set headers, so the event stream alone carries it as a query param.
const KEY = "accountable-world-token";

function readToken() {
  const url = new URL(location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    try { sessionStorage.setItem(KEY, fromUrl); } catch (e) { /* storage blocked: keep it in memory */ }
    url.searchParams.delete("token");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
    return fromUrl;
  }
  try { return sessionStorage.getItem(KEY) || ""; } catch (e) { return ""; }
}

export const token = readToken();

export function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { "X-World-Token": token });
  if ((opts.method || "GET").toUpperCase() === "POST" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  return fetch(path, Object.assign({}, opts, { headers, credentials: "same-origin" }));
}

export function stream(path) {
  return new EventSource(path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token));
}
