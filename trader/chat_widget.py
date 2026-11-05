"""The "Ask" chat panel embedded in the rung sheet. Talks to POST /chat (see trader/server.py)."""

WIDGET = r"""
<style>
#ask-btn { position:fixed; right:20px; bottom:20px; z-index:50; border:0; border-radius:999px; padding:12px 18px;
  background:var(--ink); color:var(--bg); font:600 15px/1 -apple-system, "Segoe UI", Roboto, sans-serif; cursor:pointer;
  box-shadow:0 4px 14px rgba(0,0,0,.18) }
#ask { position:fixed; right:20px; bottom:20px; z-index:51; width:420px; max-width:calc(100vw - 24px); height:min(640px, calc(100vh - 40px));
  display:none; flex-direction:column; background:var(--card); color:var(--ink); border:1px solid var(--rule); border-radius:14px;
  box-shadow:0 10px 40px rgba(0,0,0,.22); overflow:hidden }
#ask.open { display:flex } #ask.open + #ask-btn, #ask-btn.hidden { display:none }
#ask header { display:flex; align-items:center; gap:8px; padding:12px 14px; border-bottom:1px solid var(--rule) }
#ask header b { flex:1; font-size:16px }
#ask header button { border:0; background:none; color:var(--muted); font-size:14px; cursor:pointer; padding:4px 6px }
#ask-log { flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:12px; font-size:15px }
.m { max-width:92%; padding:9px 12px; border-radius:12px; line-height:1.45; overflow-wrap:anywhere }
.m.user { align-self:flex-end; background:var(--ink); color:var(--bg); white-space:pre-wrap }
.m.model { align-self:flex-start; background:var(--bg); border:1px solid var(--rule) }
.m.model p { margin:0 0 8px } .m.model p:last-child, .m.model ul:last-child, .m.model ol:last-child { margin-bottom:0 }
.m.model ul, .m.model ol { margin:0 0 8px; padding-left:20px } .m.model code { font-size:13px }
.m.model a { color:inherit } .m.err { align-self:flex-start; color:var(--sell); font-size:14px }
.src { margin-top:8px; padding-top:6px; border-top:1px solid var(--rule); font-size:12px; color:var(--muted) }
.src a { color:var(--muted); margin-right:8px }
.m.wait { color:var(--muted); font-style:italic }
#ask-hint { color:var(--muted); font-size:14px } #ask-hint button { display:block; width:100%; text-align:left; margin-top:8px;
  padding:8px 10px; border:1px solid var(--rule); border-radius:8px; background:var(--bg); color:var(--ink); font:inherit; cursor:pointer }
#ask form { display:flex; gap:8px; padding:10px; border-top:1px solid var(--rule) }
#ask textarea { flex:1; resize:none; height:44px; max-height:140px; padding:10px; border:1px solid var(--rule); border-radius:10px;
  background:var(--bg); color:var(--ink); font:15px/1.35 -apple-system, "Segoe UI", Roboto, sans-serif }
#ask form button { border:0; border-radius:10px; padding:0 16px; background:var(--ink); color:var(--bg); font-weight:600; cursor:pointer }
#ask form button:disabled { opacity:.4; cursor:default }
@media print { #ask, #ask-btn { display:none !important } }
</style>
<div id="ask" role="dialog" aria-label="Ask about your stocks">
  <header><b>Ask about your stocks</b><button id="ask-clear" title="Start over">Clear</button><button id="ask-close" title="Close">✕</button></header>
  <div id="ask-log"></div>
  <form id="ask-form"><textarea id="ask-q" placeholder="Ask a question…" aria-label="Question"></textarea><button id="ask-send">Send</button></form>
</div>
<button id="ask-btn">Ask AI</button>
<script>
(() => {
  const $ = id => document.getElementById(id), box = $("ask"), log = $("ask-log"), q = $("ask-q"), send = $("ask-send");
  const KEY = "ask-history", SUGGEST = ["Which positions need action today, and why?",
    "Any recent news on my act-now stocks?", "Why are positions on the review list?", "How does the rung system decide share counts?"];
  let hist = []; try { hist = JSON.parse(sessionStorage.getItem(KEY)) || []; } catch (e) {}
  const save = () => sessionStorage.setItem(KEY, JSON.stringify(hist.slice(-40)));
  const esc = s => s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function inline(s) {
    return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  function md(text) {          // just enough markdown: paragraphs, bullet/numbered lists, bold, code, links
    let out = "", list = null;
    const close = () => { if (list) { out += `</${list}>`; list = null; } };
    for (const line of text.split("\n")) {
      const b = line.match(/^\s*[-*•]\s+(.*)/), n = line.match(/^\s*\d+[.)]\s+(.*)/);
      if (b || n) { const t = b ? "ul" : "ol"; if (list !== t) { close(); out += `<${t}>`; list = t; } out += `<li>${inline((b || n)[1])}</li>`; }
      else if (line.trim()) { close(); out += `<p>${inline(line.replace(/^#+\s*/, ""))}</p>`; }
      else close();
    }
    close(); return out;
  }
  function bubble(m) {
    const d = document.createElement("div"); d.className = "m " + m.role;
    if (m.role === "model") {
      d.innerHTML = md(m.text);
      if (m.sources && m.sources.length) d.innerHTML += '<div class="src">Sources: ' + m.sources.slice(0, 6).map(s =>
        `<a href="${esc(s.uri)}" target="_blank" rel="noopener">${esc(s.title)}</a>`).join("") + "</div>";
    } else d.textContent = m.text;
    log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
  }
  function note(text, cls) { const d = document.createElement("div"); d.className = "m " + cls; d.textContent = text;
    log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }
  function render() {
    log.innerHTML = "";
    if (!hist.length) {
      const h = document.createElement("div"); h.id = "ask-hint";
      h.innerHTML = "Ask about today's orders, a position, or news on a stock. Answers use this sheet's data plus a web search.";
      SUGGEST.forEach(s => { const b = document.createElement("button"); b.type = "button"; b.textContent = s;
        b.onclick = () => { q.value = s; ask(); }; h.appendChild(b); });
      log.appendChild(h);
    }
    hist.forEach(bubble);
  }
  async function ask() {
    const text = q.value.trim(); if (!text || send.disabled) return;
    if (location.protocol === "file:") { note("The chat needs the app server. Run: python -m trader serve, then open http://localhost:8000", "err"); return; }
    if (!hist.length) log.innerHTML = "";
    hist.push({role: "user", text}); bubble(hist[hist.length - 1]); q.value = ""; send.disabled = true;
    const wait = note("Thinking…", "model wait");
    try {
      const r = await fetch("/chat", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({messages: hist.map(m => ({role: m.role, text: m.text}))})});
      const data = await r.json().catch(() => ({error: `Server error ${r.status}`}));
      wait.remove();
      if (!r.ok || data.error) { hist.pop(); note(data.error || `Server error ${r.status}`, "err"); q.value = text; }
      else { hist.push({role: "model", text: data.reply, sources: data.sources}); bubble(hist[hist.length - 1]); }
    } catch (e) { wait.remove(); hist.pop(); note("Couldn't reach the server. Is it running?", "err"); q.value = text; }
    save(); send.disabled = false; q.focus();
  }
  $("ask-form").onsubmit = e => { e.preventDefault(); ask(); };
  q.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } };
  $("ask-btn").onclick = () => { box.classList.add("open"); $("ask-btn").classList.add("hidden"); render(); q.focus(); };
  $("ask-close").onclick = () => { box.classList.remove("open"); $("ask-btn").classList.remove("hidden"); };
  $("ask-clear").onclick = () => { hist = []; save(); render(); q.focus(); };
})();
</script>
"""
