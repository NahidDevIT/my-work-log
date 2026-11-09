// My Work Log — service worker for the installed desktop app (http://127.0.0.1:8765).
// Always uses the live dashboard; if the dashboard is not running it shows a small "start it" page.
const OFFLINE = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My Work Log</title><body style="margin:0;display:grid;place-items:center;height:100vh;background:#0f1115;color:#e6e8ec;font:15px system-ui,sans-serif;text-align:center">
<div><h2 style="margin:0 0 8px">My Work Log is not running</h2><p style="color:#8b93a1;margin:0 0 16px">Start it from the app menu, or run <code>./start.sh</code>, then reload.</p>
<button onclick="location.reload()" style="font:inherit;font-weight:600;border:0;border-radius:10px;padding:10px 16px;background:#10b981;color:#05140e">Reload</button></div>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.mode !== "navigate") return;                     // API calls etc. go straight to the server
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, {headers: {"Content-Type": "text/html; charset=utf-8"}})));
});
