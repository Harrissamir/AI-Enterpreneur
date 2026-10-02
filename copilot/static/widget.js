/*!
 * Business Copilot widget — one script tag, no dependencies.
 *
 *   <script src="https://YOUR-API/widget.js" data-persona="harris_sons" async></script>
 *
 * Optional attributes: data-api (API base URL; defaults to where this script is served from),
 * data-accent (hex colour), data-position ("right" | "left"), data-open ("true" to open on load).
 * JavaScript: window.BusinessCopilot.open() / .close() / .ask("question").
 */
(function () {
  "use strict";
  if (window.BusinessCopilot) return;

  var script = document.currentScript || document.querySelector('script[src*="widget.js"][data-persona]');
  if (!script) return;
  var PERSONA = script.getAttribute("data-persona") || "harris_sons";
  var API = (script.getAttribute("data-api") || new URL(script.src).origin).replace(/\/$/, "");
  var POSITION = script.getAttribute("data-position") === "left" ? "left" : "right";
  var STORE_KEY = "bcopilot:" + PERSONA;

  function load() {
    try { return JSON.parse(sessionStorage.getItem(STORE_KEY)) || null; } catch (e) { return null; }
  }
  function save() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* storage blocked */ }
  }
  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "s-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  var state = load() || { session: uid(), history: [], items: [] };
  var config = null;
  var busy = false;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // Minimal, safe markdown: escape first, then bold / italics / links / lists / headings.
  function md(src) {
    var lines = esc(src).split(/\n/), out = [], list = false;
    lines.forEach(function (line) {
      var item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
      if (item) { if (!list) { out.push("<ul>"); list = true; } out.push("<li>" + inline(item[1]) + "</li>"); return; }
      if (list) { out.push("</ul>"); list = false; }
      var h = line.match(/^#{1,4}\s+(.*)$/);
      if (h) { out.push("<p class=h>" + inline(h[1]) + "</p>"); return; }
      if (line.trim()) out.push("<p>" + inline(line) + "</p>");
    });
    if (list) out.push("</ul>");
    return out.join("");
  }
  function inline(s) {
    return s
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  }

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif}",
    ".launch{position:fixed;bottom:20px;" + POSITION + ":20px;z-index:2147483000;display:flex;align-items:center;gap:8px;border:0;border-radius:999px;padding:12px 18px 12px 14px;background:var(--a);color:#fff;font-size:15px;font-weight:600;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.22);transition:transform .15s}",
    ".launch:hover{transform:translateY(-2px)}",
    ".launch svg{width:22px;height:22px}",
    ".panel{position:fixed;bottom:20px;" + POSITION + ":20px;z-index:2147483001;width:380px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 40px);display:none;flex-direction:column;background:#fff;color:#1b1f24;border-radius:16px;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.28);border:1px solid rgba(0,0,0,.08)}",
    ".panel.open{display:flex}",
    ".head{background:var(--a);color:#fff;padding:14px 16px;display:flex;align-items:flex-start;gap:10px}",
    ".head .t{flex:1;min-width:0}",
    ".head b{display:block;font-size:15px}",
    ".head .sub{display:block;font-size:12px;opacity:.85;margin-top:2px}",
    ".badge{font-size:10px;font-weight:700;letter-spacing:.06em;border:1px solid rgba(255,255,255,.6);border-radius:4px;padding:1px 5px;margin-left:6px;vertical-align:2px}",
    ".x{background:transparent;border:0;color:#fff;font-size:22px;line-height:1;cursor:pointer;padding:0 2px;opacity:.85}",
    ".log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;background:#f6f7f9}",
    ".m{max-width:88%;padding:10px 12px;border-radius:12px;font-size:14px;line-height:1.45;word-wrap:break-word}",
    ".m p{margin:0 0 6px}.m p:last-child{margin:0}.m ul{margin:4px 0 6px;padding-left:18px}.m li{margin:2px 0}.m .h{font-weight:700}",
    ".m a{color:inherit;text-decoration:underline}",
    ".bot{align-self:flex-start;background:#fff;border:1px solid #e3e6ea}",
    ".me{align-self:flex-end;background:var(--a);color:#fff}",
    ".err{align-self:center;background:#fff4f2;border:1px solid #f3c9c1;color:#8a2a17;font-size:13px}",
    ".card{align-self:stretch;background:#fff;border:1px solid #e3e6ea;border-left:4px solid var(--a);border-radius:10px;padding:12px 14px;font-size:13.5px;line-height:1.45}",
    ".card p{margin:0 0 6px}.card ul{margin:2px 0 8px;padding-left:18px}.card .h{font-weight:700;font-size:14.5px}",
    ".cta{align-self:flex-start;display:inline-block;background:var(--a);color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:9px 14px;border-radius:8px}",
    ".note{align-self:center;font-size:12px;color:#3d6b45;background:#eef7ef;border-radius:999px;padding:4px 10px}",
    ".chips{display:flex;flex-wrap:wrap;gap:6px}",
    ".chip{border:1px solid #cfd5dc;background:#fff;border-radius:999px;padding:6px 10px;font-size:12.5px;cursor:pointer;color:#1b1f24;text-align:left}",
    ".chip:hover{border-color:var(--a)}",
    ".dots{align-self:flex-start;display:flex;gap:4px;padding:12px}",
    ".dots i{width:6px;height:6px;border-radius:50%;background:#9aa3ad;animation:b 1s infinite}",
    ".dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}",
    "@keyframes b{0%,80%,100%{opacity:.3}40%{opacity:1}}",
    "form{display:flex;gap:8px;padding:10px;border-top:1px solid #e3e6ea;background:#fff}",
    "textarea{flex:1;resize:none;border:1px solid #cfd5dc;border-radius:10px;padding:9px 10px;font-size:14px;max-height:120px;min-height:40px;color:#1b1f24;background:#fff;outline:none}",
    "textarea:focus{border-color:var(--a)}",
    ".send{border:0;border-radius:10px;background:var(--a);color:#fff;font-weight:600;padding:0 14px;cursor:pointer;font-size:14px}",
    ".send:disabled{opacity:.5;cursor:default}",
    ".foot{font-size:11px;color:#6b7480;text-align:center;padding:0 10px 9px;background:#fff}",
    ".foot a{color:#6b7480}",
    "@media (max-width:480px){.panel{inset:0;width:100%;max-width:100%;height:100%;max-height:100%;border-radius:0}}"
  ].join("");

  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  var host = document.createElement("div");
  host.setAttribute("data-business-copilot", PERSONA);
  var root = host.attachShadow({ mode: "open" });
  var els = {};

  function build() {
    var accent = script.getAttribute("data-accent") || config.accent || "#1F3A5F";
    root.innerHTML =
      "<style>" + CSS + "</style>" +
      '<div style="--a:' + esc(accent) + '">' +
      '<button class="launch" type="button" aria-label="Open ' + esc(config.assistant_name) + '">' + ICON + "<span>Ask us</span></button>" +
      '<section class="panel" role="dialog" aria-label="' + esc(config.assistant_name) + '">' +
      '<div class="head"><div class="t"><b>' + esc(config.assistant_name) + '<span class="badge">AI</span></b><span class="sub">' + esc(config.tagline || config.brand) + "</span></div>" +
      '<button class="x" type="button" aria-label="Close">&times;</button></div>' +
      '<div class="log" aria-live="polite"></div>' +
      '<form><textarea rows="1" placeholder="Type your question…" aria-label="Message" maxlength="2000"></textarea><button class="send" type="submit">Send</button></form>' +
      '<div class="foot">AI assistant · general information, not advice on your specific case · <a href="' + esc(config.booking_url) + '" target="_blank" rel="noopener">Talk to a person</a></div>' +
      "</section></div>";
    els.launch = root.querySelector(".launch");
    els.panel = root.querySelector(".panel");
    els.log = root.querySelector(".log");
    els.form = root.querySelector("form");
    els.input = root.querySelector("textarea");
    els.send = root.querySelector(".send");

    els.launch.addEventListener("click", open);
    root.querySelector(".x").addEventListener("click", close);
    els.form.addEventListener("submit", function (e) { e.preventDefault(); ask(els.input.value); });
    els.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(els.input.value); }
    });
    els.input.addEventListener("input", function () {
      els.input.style.height = "auto";
      els.input.style.height = Math.min(els.input.scrollHeight, 120) + "px";
    });
    root.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    render();
  }

  function addEl(cls, html) {
    var d = document.createElement("div");
    d.className = cls;
    d.innerHTML = html;
    els.log.appendChild(d);
    els.log.scrollTop = els.log.scrollHeight;
    return d;
  }

  function renderItem(it) {
    if (it.kind === "user") addEl("m me", esc(it.text).replace(/\n/g, "<br>"));
    else if (it.kind === "bot") addEl("m bot", md(it.text));
    else if (it.kind === "error") addEl("m err", esc(it.text));
    else if (it.kind === "role_brief") addEl("card", md(it.markdown));
    else if (it.kind === "lead_captured") addEl("note", "✓ Details sent — we'll reply by email");
    else if (it.kind === "book_call") {
      var a = document.createElement("a");
      a.className = "cta";
      a.href = it.url; a.target = "_blank"; a.rel = "noopener";
      a.textContent = it.label || "Book a call";
      els.log.appendChild(a);
    }
  }

  function render() {
    els.log.innerHTML = "";
    addEl("m bot", md(config.greeting));
    state.items.forEach(renderItem);
    if (!state.items.length && config.starter_questions && config.starter_questions.length) {
      var chips = addEl("chips", "");
      config.starter_questions.forEach(function (q) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "chip"; b.textContent = q;
        b.addEventListener("click", function () { ask(q); });
        chips.appendChild(b);
      });
    }
    els.log.scrollTop = els.log.scrollHeight;
  }

  function push(item) { state.items.push(item); renderItem(item); save(); }

  function ask(text) {
    text = String(text || "").trim();
    if (!text || busy || !config) return;
    open();
    if (!state.items.length) render(); // clears starter chips
    var chips = root.querySelector(".chips"); if (chips) chips.remove();
    els.input.value = ""; els.input.style.height = "auto";
    push({ kind: "user", text: text });
    state.history.push({ role: "user", content: text });
    busy = true; els.send.disabled = true;
    var dots = addEl("dots", "<i></i><i></i><i></i>");

    fetch(API + "/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona: PERSONA, session_id: state.session, messages: state.history.slice(-20) })
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        dots.remove();
        if (!res.ok) {
          state.history.pop();
          push({ kind: "error", text: res.j.error || res.j.detail || "Something went wrong. Please try again." });
          return;
        }
        state.history.push({ role: "assistant", content: res.j.reply });
        push({ kind: "bot", text: res.j.reply });
        (res.j.actions || []).forEach(function (a) {
          if (a.type === "book_call") push({ kind: "book_call", url: a.url, label: a.label });
          else if (a.type === "role_brief") push({ kind: "role_brief", markdown: a.markdown });
          else if (a.type === "lead_captured") push({ kind: "lead_captured" });
        });
      })
      .catch(function () {
        dots.remove();
        state.history.pop();
        push({ kind: "error", text: "Can't reach the assistant right now. You can contact us at " + config.contact_url });
      })
      .then(function () { busy = false; els.send.disabled = false; save(); els.input.focus(); });
  }

  function open() { if (!els.panel) return; els.panel.classList.add("open"); els.launch.style.display = "none"; setTimeout(function () { els.input.focus(); }, 30); }
  function close() { if (!els.panel) return; els.panel.classList.remove("open"); els.launch.style.display = ""; els.launch.focus(); }

  window.BusinessCopilot = { open: open, close: close, ask: ask };

  // Never sit on top of the host site's own bottom bars (cookie banners, badges):
  // lift the launcher above any visible fixed element docked at the bottom of the screen.
  var dodgeTimer = null;
  function dodge() {
    if (!els.launch) return;
    var vh = window.innerHeight, vw = window.innerWidth, lift = 0;
    var nodes = document.body ? document.body.querySelectorAll("*") : [];
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el === host) continue;
      var cs = window.getComputedStyle(el);
      if (cs.position !== "fixed" && cs.position !== "sticky") continue;
      if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) continue;
      var r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0 || r.height > vh * 0.6) continue;
      if (vh - r.bottom > 40) continue; // not docked at the bottom
      var nearSide = POSITION === "right" ? r.right > vw - 260 : r.left < 260;
      if (!nearSide) continue;
      lift = Math.max(lift, vh - r.top);
    }
    els.launch.style.bottom = (lift ? lift + 12 : 20) + "px";
  }
  function scheduleDodge() { clearTimeout(dodgeTimer); dodgeTimer = setTimeout(dodge, 250); }

  fetch(API + "/v1/personas/" + encodeURIComponent(PERSONA))
    .then(function (r) { if (!r.ok) throw new Error("persona"); return r.json(); })
    .then(function (c) {
      config = c;
      (document.body || document.documentElement).appendChild(host);
      build();
      dodge();
      window.addEventListener("resize", scheduleDodge);
      if (window.MutationObserver) {
        new MutationObserver(scheduleDodge).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden"] });
      }
      if (script.getAttribute("data-open") === "true") open();
    })
    .catch(function () { /* fail silently: never break the host website */ });
})();
