"use strict";
/* X Reply Radar front end: plain JS, no build step. Strings live in i18n.js. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const S = { view: "radar", status: null, lang: "zh", picks: new Map(), busyViews: new Set() };

// ---------- helpers ----------

function t(key, params = {}) {
  const table = I18N[S.lang] || I18N.zh;
  let s = table[key] ?? I18N.zh[key] ?? I18N.en[key] ?? key;
  for (const [k, v] of Object.entries(params)) s = s.replaceAll(`{${k}}`, v);
  return s;
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
function h(html) { const tpl = document.createElement("template"); tpl.innerHTML = html.trim(); return tpl.content.firstElementChild; }

function num(n) {
  if (n == null) return null;
  if (S.lang === "zh") {
    if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, "") + "亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万";
    return String(n);
  }
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}
function ago(iso) {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (m < 1) return t("time.now");
  if (m < 60) return t("time.m", { n: m });
  if (m < 1440) return t("time.h", { n: Math.floor(m / 60) });
  return t("time.d", { n: Math.floor(m / 1440) });
}
// "just now" / "5 minutes ago": for sentences, where ago() is for compact timestamps
function since(iso) {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  return m < 1 ? t("time.now") : t("time.ago", { t: ago(iso) });
}
// X's weighted length: CJK and emoji count 2, links 23 (same rule as publisher.x_length)
function xlen(text) {
  let n = 0;
  for (const ch of (text || "").replace(/https?:\/\/\S+/g, "x".repeat(23))) {
    const cp = ch.codePointAt(0);
    const light = cp <= 0x10ff || (cp >= 0x2000 && cp <= 0x200d) || (cp >= 0x2010 && cp <= 0x201f) || (cp >= 0x2032 && cp <= 0x2037);
    n += light ? 1 : 2;
  }
  return n;
}

async function api(path, body, opts = {}) {
  const init = body === undefined ? {} : body instanceof FormData
    ? { method: "POST", body }
    : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, { ...init, ...opts });
  let data = null;
  try { data = await r.json(); } catch { /* empty body */ }
  if (!r.ok) {
    const code = (data && (data.detail || data.error)) || `HTTP ${r.status}`;
    const msg = typeof code === "string" ? code : JSON.stringify(code);
    throw new Error(I18N[S.lang]?.["err." + msg] ? t("err." + msg) : msg);
  }
  return data;
}

function toast(msg, kind = "") {
  const el = h(`<div class="toast ${kind}">${esc(msg)}</div>`);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "err" ? 6000 : kind === "long" ? 9000 : 2600);
}
function toastLink(msg, url, label) {
  const el = h(`<div class="toast">${esc(msg)} <a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer" style="color:inherit;font-weight:600">${esc(label)} ↗</a></div>`);
  $("a", el).addEventListener("click", () => setTimeout(() => el.remove(), 300));
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 15000);
}
async function guard(btn, fn) {
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.classList.add("spin"); }
  try { return await fn(); }
  catch (e) { toast(e.message, "err"); }
  finally { if (btn && btn.isConnected) { btn.disabled = false; btn.classList.remove("spin"); btn.textContent = label; } }
}
async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.cssText = "position:fixed;opacity:0"; document.body.append(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  if (btn) { const l = btn.textContent; btn.textContent = t("common.copied"); btn.classList.add("done"); setTimeout(() => { btn.textContent = l; btn.classList.remove("done"); }, 1300); }
}
function autosize(ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, 480) + "px"; }

// ---------- sending ----------

async function send(payload) {
  if (S.status?.demo) throw new Error(t("err.demo_mode"));
  // intent: X opens in a new tab with the text filled in. Open the tab now, inside the click,
  // so popup blockers allow it; point it at X once the server answers.
  const intent = (S.status?.channel || "intent") === "intent";
  const win = intent ? window.open("about:blank", "_blank") : null;
  // X has no "quote" link: the post opens instead, with your text on the clipboard to paste
  const quoting = intent && payload.kind === "quote";
  if (quoting) copy(payload.text);
  try {
    const r = await api("/api/send", payload);
    if (r.intent_url) {
      let w = win;
      if (!w) { w = window.open(r.intent_url, "_blank"); if (w) w.opener = null; }
      else { w.opener = null; w.location.href = r.intent_url; }
      const msg = quoting ? t("toast.quote_intent") : t("toast.intent");
      if (w) toast(msg, quoting ? "long" : "");
      else toastLink(t("toast.popup_blocked"), r.intent_url, t("toast.open_x"));  // popup blocked: let a real click open it
    } else toast(t("toast.queued"));
    loadStatus();
    return r;
  } catch (e) { if (win) win.close(); throw e; }
}

function fitBadge(score) {
  if (score == null) return "";
  const low = score < Number(S.status?.fit_min || 7);
  return `<span class="fit ${low ? "low" : ""}" title="${esc(t("fit.tip"))}">${Number(score).toFixed(1).replace(/\.0$/, "")}</span>`;
}

/* A text box you can edit and send: used for drafts, quote posts and posts on trends. */
function editor(d, { onDone } = {}) {
  const kind = d.kind_code || d.kind || "post";
  const el = h(`
    <div class="editor">
      <div class="label"><span>${esc(t("kind." + kind))}${d.angle ? " · " + esc(d.angle) : ""}</span>${fitBadge(d.score)}</div>
      <textarea rows="1"></textarea>
      ${d.url ? `<div class="basis">${esc(t(kind === "link" ? "draft.source" : "draft.quoting"))}: <a class="link" target="_blank" rel="noopener noreferrer" href="${esc(safeUrl(d.url))}">${esc(d.source || d.url)}</a></div>` : ""}
      ${d.based_on ? `<div class="basis">${esc(d.based_on)}</div>` : ""}
      <div class="row">
        <span class="count"></span>
        <div class="btns">
          <button class="quiet" data-do="drop">${esc(t("draft.drop"))}</button>
          <button class="quiet" data-do="copy">${esc(t("common.copy"))}</button>
          <button class="pill small" data-do="polish">${esc(t("draft.polish"))}</button>
          <button class="pill small primary" data-do="send">${esc(t("send." + kind))}</button>
        </div>
      </div>
    </div>`);
  const ta = $("textarea", el);
  ta.value = d.text || "";
  // what the AI wrote, so an edit before sending becomes a learning signal (your own text has none)
  let aiText = d.id ? (d.original || d.text) : null;
  const count = $(".count", el);
  const extra = kind === "link" && d.url ? 24 : 0;  // the link added at the end counts as 23 + a line break
  const update = () => { const n = xlen(ta.value) + extra; count.textContent = `${n} / 280`; count.classList.toggle("over", n > 280); autosize(ta); };
  ta.addEventListener("input", update);
  requestAnimationFrame(update);
  $$("[data-do]", el).forEach((b) => b.addEventListener("click", () => {
    const act = b.dataset.do;
    if (act === "copy") return copy(ta.value, b);
    if (act === "polish") return guard(b, async () => {
      const r = await api("/api/polish", { text: ta.value });
      ta.value = r.text; update();
      aiText = r.text;  // the AI rewrote it: what you change from here on is a signal
      toast(r.fix || t("draft.unchanged"));
    });
    if (act === "drop") return guard(b, async () => {
      if (d.id) await api("/api/drafts/mark", { id: d.id, status: "dropped" });
      el.remove(); onDone && onDone("dropped");
    });
    if (act === "send") return guard(b, async () => {
      const text = ta.value.trim();
      if (!text) return;
      await send({ kind, text, target_id: d.target_id || null, draft_id: d.id || null, ai_text: aiText });
      el.remove(); onDone && onDone("sent");
    });
  }));
  return el;
}

// ---------- status ----------

let pollTimer = null;
const busy = (s) => s && (s.running || s.drafting || s.learning || s.task);

async function loadStatus() {
  let s;
  try { s = await api("/api/status"); } catch { return; }
  const was = S.status;
  S.status = s;
  renderStatus();
  if (was && busy(was) && !busy(s)) views[S.view].load();  // something finished: show the result
  clearTimeout(pollTimer);
  pollTimer = setTimeout(loadStatus, busy(s) ? 2500 : 20000);
}

function renderStatus() {
  const s = S.status;
  if (!s) return;
  $("#me").textContent = s.handle ? "@" + s.handle : "";
  const v = views[S.view];
  const btn = $("#action");
  const label = v.action && v.action();
  btn.hidden = !label;
  if (label) { btn.textContent = label.text; btn.disabled = !!label.disabled; }
  $("#updated").textContent = s.phase ? s.phase + "…" : (S.view === "radar" && s.last_ok ? t("status.updated", { ago: since(s.last_ok) }) : "");
  let msg = "";
  if (!s.x_ready) msg = t("notice.no_x");
  else if (s.login_expired) msg = t("notice.expired");
  else if (s.error) msg = s.error;
  else if (!s.ai_ready) msg = t("notice.no_ai");
  const n = $("#notice");
  n.hidden = !msg || S.view === "settings";
  n.innerHTML = msg ? `${esc(msg)} <button data-go="settings">${esc(t("notice.fix"))}</button>` : "";
  const q = s.queue || {};
  const dot = $('.tab[data-view="queue"] .dot');
  if (dot) { dot.hidden = !q.pending; dot.textContent = q.pending || ""; }
}

// ---------- views ----------

const views = {};

/* Hot posts */
views.radar = {
  action: () => ({ text: S.status?.running ? (S.status.phase || t("status.working")) + "…" : t("action.refresh"), disabled: S.status?.running }),
  async onAction() { await api("/api/refresh", {}); loadStatus(); },
  async load() {
    const r = await api("/api/feed");
    S.status = { ...S.status, ...r.status };
    renderStatus();
    const main = $("#view");
    if (!r.items.length) {
      main.replaceChildren(h(`<div class="empty">${esc(r.status.running ? t("radar.loading") : t("radar.empty"))}</div>`));
      return;
    }
    main.replaceChildren(...r.items.map(postCard));
    renderBatch();
  },
};

function postCard(p) {
  const autoSend = (S.status?.channel || "intent") !== "intent";
  const stats = [num(p.views) && `${num(p.views)} ${t("stat.views")}`, `${num(p.replies) ?? 0} ${t("stat.replies")}`, `${num(p.likes) ?? 0} ${t("stat.likes")}`].filter(Boolean).join(" · ");
  const up = p.growth_pct != null ? ` · <span class="up">↑${p.growth_pct >= 10 ? Math.round(p.growth_pct) : p.growth_pct}%</span>` : "";
  const media = p.media_type ? `<span class="media">[${esc(t("media." + p.media_type))}]</span>` : "";
  const parts = Object.entries(p.parts || {}).map(([k, v]) => `${t("part." + k)} ${v > 0 ? "+" : ""}${v}`).join("  ");
  const tip = `${parts}\n${p.measured ? t("radar.velocity", { m: p.growth_window, v: Math.round(p.vpm) }) : t("radar.avg_velocity", { v: Math.round(p.vpm) })}`;
  const el = h(`
    <article data-id="${esc(p.id)}">
      <div class="head"><span class="who"><b>${esc(p.author_name)}</b>@${esc(p.author_handle)} · ${esc(ago(p.created_at))}</span>
        ${p.hot_score != null ? `<span class="score" title="${esc(tip)}">${p.hot_score}</span>` : ""}</div>
      <div class="text">${esc(p.text)}${media}</div>
      <div class="meta">${stats}${up}</div>
      <div class="tags">${p.stage ? `<span class="stage ${esc(p.stage_key || "")}">${esc(t("stage." + (p.stage_key || "")) || p.stage)}</span>` : ""}${p.topic ? `<span>${esc(p.topic)}</span>` : ""}</div>
      <div class="replies"></div>
      <div class="extra"></div>
      <div class="foot">
        <a href="${esc(safeUrl(p.url))}" target="_blank" rel="noopener noreferrer">${esc(t("radar.open"))} ↗</a>
        <button data-act="quote">${esc(t("radar.quote"))}</button>
        <button data-act="regen">${esc(t("radar.regen"))}</button>
        <button class="less" data-act="dismiss">${esc(t("radar.dismiss"))}</button>
        <button class="less" data-act="author">${esc(t("radar.mute_author"))}</button>
        ${p.topic ? `<button class="less" data-act="topic">${esc(t("radar.mute_topic", { topic: p.topic }))}</button>` : ""}
      </div>
    </article>`);
  $(".text", el).addEventListener("click", (e) => { if (!getSelection().toString()) e.currentTarget.classList.toggle("open"); });
  renderReplies(el, p, autoSend);
  $$("[data-act]", el).forEach((b) => b.addEventListener("click", () => {
    const act = b.dataset.act;
    if (act === "quote") return guard(b, async () => {
      const r = await api("/api/quote/generate", { tweet_id: p.id });
      if (!r.draft) return toast(t("draft.skipped"));
      $(".extra", el).replaceChildren(editor(r.draft));
    });
    if (act === "regen") return guard(b, async () => {
      const r = await api("/api/replies/regenerate", { id: p.id });
      Object.assign(p, r.item);
      renderReplies(el, p, autoSend);
    });
    const value = act === "dismiss" ? p.id : act === "author" ? p.author_handle : p.topic;
    guard(b, async () => { await api("/api/feedback", { kind: act, value }); el.remove(); S.picks.delete(p.id); renderBatch(); });
  }));
  return el;
}

function renderReplies(el, p, autoSend) {
  const box = $(".replies", el);
  if (!p.reply_a || p.ai_skip) {
    const why = !S.status?.ai_ready ? t("radar.no_ai") : p.ai_skip ? t("radar.ai_skipped") : t("radar.writing");
    box.replaceChildren(h(`<div class="noreply">${esc(why)}</div>`));
    return;
  }
  box.replaceChildren(...["a", "b"].map((k) => {
    const original = p["reply_" + k];
    const picked = S.picks.get(p.id);
    const row = h(`
      <div class="reply">
        <span class="k">${k.toUpperCase()}${autoSend ? `<input type="checkbox" title="${esc(t("batch.pick"))}" ${picked && picked.choice === k ? "checked" : ""}>` : ""}</span>
        <div class="v"></div>
        <span class="acts">${fitBadge(p["fit_" + k])}<button data-r="edit">${esc(t("common.edit"))}</button><button data-r="copy">${esc(t("common.copy"))}</button><button class="go" data-r="send">${esc(t("send.reply"))}</button></span>
      </div>`);
    const v = $(".v", row);
    let text = picked && picked.choice === k ? picked.text : original;
    v.textContent = text;
    const current = () => { const ta = $("textarea", v); return (ta ? ta.value : v.textContent).trim(); };
    $('[data-r="edit"]', row).addEventListener("click", (e) => {
      if ($("textarea", v)) return;
      const ta = h(`<textarea rows="2"></textarea>`);
      ta.value = current(); v.replaceChildren(ta); autosize(ta); ta.focus();
      ta.addEventListener("input", () => { autosize(ta); const pk = S.picks.get(p.id); if (pk && pk.choice === k) { pk.text = ta.value; } });
      e.currentTarget.hidden = true;
    });
    $('[data-r="copy"]', row).addEventListener("click", (e) => copy(current(), e.currentTarget));
    $('[data-r="send"]', row).addEventListener("click", (e) => guard(e.currentTarget, async () => {
      await send({ kind: "reply", text: current(), target_id: p.id, ai_text: original });
      el.remove(); S.picks.delete(p.id); renderBatch();
    }));
    const cb = $("input[type=checkbox]", row);
    if (cb) cb.addEventListener("change", () => {
      if (cb.checked) {
        $$(".reply input[type=checkbox]", el).forEach((o) => { if (o !== cb) o.checked = false; });
        S.picks.set(p.id, { choice: k, text: current(), original, get live() { return current(); } });
      } else S.picks.delete(p.id);
      renderBatch();
    });
    return row;
  }));
}

function renderBatch() {
  const bar = $("#batch");
  const n = S.picks.size;
  bar.hidden = !n || S.view !== "radar";
  if (!n) return;
  bar.innerHTML = `<span>${esc(t("batch.picked", { n }))}</span><button data-b="clear">${esc(t("batch.clear"))}</button><button class="pill" data-b="send">${esc(t("batch.send"))}</button>`;
  $('[data-b="clear"]', bar).onclick = () => { S.picks.clear(); $$(".reply input[type=checkbox]").forEach((c) => (c.checked = false)); renderBatch(); };
  $('[data-b="send"]', bar).onclick = (e) => guard(e.currentTarget, async () => {
    const items = [...S.picks.entries()].map(([id, pk]) => ({ kind: "reply", text: pk.live || pk.text, target_id: id, ai_text: pk.original }));
    const r = await api("/api/send/batch", { items });
    toast(t("batch.queued", { n: r.items.length }));
    for (const id of S.picks.keys()) $(`article[data-id="${CSS.escape(id)}"]`)?.remove();
    S.picks.clear(); renderBatch(); loadStatus();
  });
}

/* Trends */
views.trends = {
  action: () => ({ text: S.status?.task === "trends" ? t("status.working") + "…" : t("action.refresh_trends"), disabled: S.status?.task === "trends" || S.status?.running }),
  async onAction() { await api("/api/trends/refresh", {}); loadStatus(); },
  async load() {
    const r = await api("/api/trends");
    const main = $("#view");
    if (!r.items.length) { main.replaceChildren(h(`<div class="empty">${esc(t("trends.empty"))}</div>`)); return; }
    const list = h(`<div class="list"></div>`);
    for (const it of r.items) {
      const row = h(`
        <div class="item">
          <span class="rank">${it.rank + 1}</span>
          <div class="body">
            <div class="title">${esc(it.name)}</div>
            <div class="small">${esc([it.context, it.posts].filter(Boolean).join(" · "))}</div>
            <div class="foot"><a href="https://x.com/search?q=${encodeURIComponent(it.name)}&src=trend_click" target="_blank" rel="noopener noreferrer">${esc(t("trends.search"))} ↗</a><button data-a="write">${esc(t("trends.write"))}</button></div>
            <div class="extra"></div>
          </div>
        </div>`);
      $('[data-a="write"]', row).addEventListener("click", (e) => guard(e.currentTarget, async () => {
        const res = await api("/api/post/generate", { topic: it.name, context: [it.context, it.posts].filter(Boolean).join(" · ") });
        if (!res.draft) return toast(t("draft.skipped"));
        $(".extra", row).replaceChildren(editor(res.draft));
      }));
      list.append(row);
    }
    main.replaceChildren(h(`<p class="sub">${esc(t("trends.sub", { ago: since(r.fetched_at ? new Date(Number(r.fetched_at) * 1000).toISOString() : null) }))}</p>`), list);
  },
};

/* Official news: watched accounts + feeds */
views.news = {
  action: () => ({ text: S.status?.task === "watch" || S.status?.phase_key === "news" ? t("status.working") + "…" : t("action.refresh"), disabled: !!S.status?.task }),
  async onAction() { await api("/api/news/refresh", {}); loadStatus(); },
  async load() {
    const r = await api("/api/news");
    const main = $("#view");
    const acc = h(`
      <div>
        <h2>${esc(t("news.accounts"))}</h2>
        <div class="field" style="grid-template-columns:1fr auto"><input type="text" placeholder="${esc(t("news.accounts_ph"))}"><button class="pill">${esc(t("common.save"))}</button></div>
        <p class="sub">${esc(t("news.accounts_help"))}</p>
        <div class="watch"></div>
      </div>`);
    $("input", acc).value = r.accounts.join(", ");
    $("button", acc).addEventListener("click", (e) => guard(e.currentTarget, async () => {
      await api("/api/settings", { values: { WATCH_ACCOUNTS: $("input", acc).value } });
      await api("/api/news/refresh", {}); toast(t("common.saved")); loadStatus();
    }));
    const watch = $(".watch", acc);
    if (!r.watch.length) watch.append(h(`<div class="empty" style="padding:18px 0">${esc(r.accounts.length ? t("news.watch_empty") : t("news.no_accounts"))}</div>`));
    for (const p of r.watch) {
      const card = h(`
        <article>
          <div class="head"><span class="who"><b>${esc(p.author_name)}</b>@${esc(p.author_handle)} · ${esc(ago(p.created_at))}</span></div>
          <div class="text">${esc(p.text)}</div>
          <div class="meta">${esc([num(p.views) && num(p.views) + " " + t("stat.views"), (num(p.replies) ?? 0) + " " + t("stat.replies")].filter(Boolean).join(" · "))}</div>
          <div class="replies"></div><div class="extra"></div>
          <div class="foot"><a href="${esc(safeUrl(p.url))}" target="_blank" rel="noopener noreferrer">${esc(t("radar.open"))} ↗</a><button data-a="reply">${esc(t("news.write_reply"))}</button><button data-a="quote">${esc(t("radar.quote"))}</button></div>
        </article>`);
      $(".text", card).addEventListener("click", (e) => { if (!getSelection().toString()) e.currentTarget.classList.toggle("open"); });
      if (p.reply_a && !p.ai_skip) renderReplies(card, p, false);
      $('[data-a="reply"]', card).addEventListener("click", (e) => guard(e.currentTarget, async () => {
        const res = await api("/api/replies/regenerate", { id: p.id });
        Object.assign(p, res.item); renderReplies(card, p, false);
      }));
      $('[data-a="quote"]', card).addEventListener("click", (e) => guard(e.currentTarget, async () => {
        const res = await api("/api/quote/generate", { tweet_id: p.id });
        if (!res.draft) return toast(t("draft.skipped"));
        $(".extra", card).replaceChildren(editor(res.draft));
      }));
      watch.append(card);
    }
    const feed = h(`<div><h2>${esc(t("news.feeds"))}</h2><p class="sub">${esc(t("news.feeds_help", { n: (r.sources.sources || []).length }))}</p><div class="list"></div></div>`);
    const list = $(".list", feed);
    if (!r.news.length) list.append(h(`<div class="empty" style="padding:18px 0">${esc(t("news.empty"))}</div>`));
    for (const n of r.news) {
      const row = h(`
        <div class="item"><div class="body">
          <div class="small">${esc(n.source)} · ${esc(ago(n.published || n.first_seen))}${n.picked_at ? " · " + esc(t("news.used")) : ""}</div>
          <div class="title"><a href="${esc(safeUrl(n.url))}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a></div>
          ${n.summary ? `<div class="desc">${esc(n.summary)}</div>` : ""}
          <div class="foot"><button data-a="quote">${esc(t("news.quote"))}</button></div>
          <div class="extra"></div>
        </div></div>`);
      $('[data-a="quote"]', row).addEventListener("click", (e) => guard(e.currentTarget, async () => {
        const res = await api("/api/quote/generate", { news_url: n.url });
        if (!res.draft) return toast(t("draft.skipped"));
        $(".extra", row).replaceChildren(editor(res.draft));
      }));
      list.append(row);
    }
    main.replaceChildren(acc, feed);
  },
};

/* Follow-back finder */
const S_FOLLOW = { picked: new Set() };

function markWords(text, words) {
  let html = esc(text);
  for (const w of words) {
    if (!w) continue;
    const e = esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp(e, "gi"), (m) => `<mark>${m}</mark>`);
  }
  return html;
}
function followStats(c) {
  const diff = c.following - c.followers;
  return `${esc(t("follow.following"))} <b>${num(c.following)}</b> · ${esc(t("follow.followers"))} <b>${num(c.followers)}</b>` +
    ` · ${esc(t("follow.diff"))} <b class="${diff >= 0 ? "ok" : "bad"}">${diff >= 0 ? "+" : "−"}${num(Math.abs(diff))}</b>`;
}
function avatar(c) {
  return c.avatar ? `<img class="av" src="${esc(safeUrl(c.avatar))}" alt="" referrerpolicy="no-referrer" loading="lazy">` : `<span class="av"></span>`;
}

async function followOne(c, btn) {
  const auto = (S.status?.channel || "intent") !== "intent";
  if (S.status?.demo) throw new Error(t("err.demo_mode"));
  if (auto) {
    const r = await api("/api/follow/queue", { ids: [c.user_id] });
    toast(r.queued ? t("toast.follow_queued", { n: r.queued }) : t("follow.not_eligible"));
    return;
  }
  const win = window.open("about:blank", "_blank");
  try {
    const r = await api("/api/follow/open", { id: c.user_id });
    if (win) { win.opener = null; win.location.href = r.intent_url; toast(t("toast.follow_intent")); }
    else toastLink(t("toast.popup_blocked"), r.intent_url, t("toast.open_x"));
  } catch (e) { if (win) win.close(); throw e; }
}

views.follow = {
  action: () => ({ text: S.status?.task === "follow_search" ? t("status.working") + "…" : t("action.follow_search"), disabled: !!S.status?.task }),
  async onAction() {
    const box = $("#fkw");
    await api("/api/follow/search", box ? { keywords: box.value } : {});
    loadStatus();
  },
  async load() {
    const r = await api("/api/follow");
    const main = $("#view");
    const q = r.queue;
    const auto = r.channel !== "intent";
    const words = r.keywords;
    S_FOLLOW.picked = new Set([...S_FOLLOW.picked].filter((id) => r.eligible.some((c) => c.user_id === id)));

    const blocked = q.blocked ? " · " + t("follow.blocked." + q.blocked, { s: q.wait_sec, m: Math.ceil(q.wait_sec / 60) }) : "";
    const head = h(`
      <div class="fhead">
        <div class="field" style="grid-template-columns:1fr auto;margin:14px 0 0">
          <input id="fkw" type="text" placeholder="${esc(t("follow.keywords_ph"))}">
          <button class="pill primary" data-f="search">${esc(t("action.follow_search"))}</button>
        </div>
        <p class="sub" style="margin-top:8px">${esc(t("follow.rules", { r: r.rules.max_ratio, n: r.rules.min_following, p: r.rules.min_posts }))}
          <button class="link" data-go="settings" data-sec="follow">${esc(t("follow.change_rules"))}</button></p>
        <div class="fbar">
          <span>${esc(t("follow.quota", { d: q.day, md: q.max_day, h: q.hour, mh: q.max_hour }))}${q.queued ? " · " + esc(t("follow.queued_n", { n: q.queued })) : ""}${esc(blocked)}</span>
          <span>${esc(t("follow.stats", { f: r.stats.by_status.followed || 0, b: r.stats.followed_back }))}</span>
        </div>
      </div>`);
    $("#fkw", head).value = words.join(", ");
    $('[data-f="search"]', head).onclick = (e) => guard(e.currentTarget, async () => {
      const res = await api("/api/follow/search", { keywords: $("#fkw", head).value });
      toast(res.started ? t("follow.searching") : t("learn.busy")); loadStatus();
    });
    $('[data-go="settings"]', head).addEventListener("click", () => { settingsSection = "follow"; try { localStorage.setItem("settingsSection", "follow"); } catch {} });

    // eligible
    const list = h(`<div class="flist"></div>`);
    const batch = h(`<div class="fsel">${auto ? `<label class="toggle"><input type="checkbox" data-f="all"> ${esc(t("follow.select_all"))}</label>` : ""}
      <span class="sub" style="margin:0">${esc(t("follow.eligible", { n: r.eligible.length }))}${r.searched_at ? " · " + esc(t("follow.searched", { ago: since(r.searched_at) })) : ""}</span>
      <button class="pill primary small" data-f="batch" ${auto ? "" : "disabled"}></button>
      ${auto ? "" : `<span class="fnote">${esc(t("follow.batch_intent"))} <button class="link" data-go="settings" data-sec="post">${esc(t("follow.change_channel"))}</button></span>`}</div>`);
    const renderBatch = () => {
      const n = S_FOLLOW.picked.size;
      const b = $('[data-f="batch"]', batch);
      b.textContent = t("follow.batch", { n });
      b.disabled = !auto || !n;
      const all = $('[data-f="all"]', batch);
      if (all) all.checked = n > 0 && n === Math.min(r.eligible.length, SHOW);
    };
    const chan = $('[data-sec="post"]', batch);
    if (chan) chan.addEventListener("click", () => { settingsSection = "post"; try { localStorage.setItem("settingsSection", "post"); } catch {} });
    if ($('[data-f="all"]', batch)) $('[data-f="all"]', batch).onchange = (e) => {
      S_FOLLOW.picked = e.target.checked ? new Set(r.eligible.slice(0, SHOW).map((c) => c.user_id)) : new Set();
      $$("input[data-pick]", list).forEach((cb) => (cb.checked = e.target.checked));
      renderBatch();
    };
    $('[data-f="batch"]', batch).onclick = (e) => guard(e.currentTarget, async () => {
      const res = await api("/api/follow/queue", { ids: [...S_FOLLOW.picked] });
      toast(t("toast.follow_queued", { n: res.queued }));
      S_FOLLOW.picked.clear(); views.follow.load(); loadStatus();
    });
    const SHOW = 200;  // the rest appear as you follow or skip people
    for (const c of r.eligible.slice(0, SHOW)) {
      const row = h(`
        <div class="frow">
          ${auto ? `<input type="checkbox" data-pick="${esc(c.user_id)}" ${S_FOLLOW.picked.has(c.user_id) ? "checked" : ""}>` : ""}
          ${avatar(c)}
          <div class="fbody">
            <div class="fname"><b>${esc(c.name)}</b> <span>@${esc(c.handle)}</span>
              ${c.followed_by ? `<span class="chip sent">${esc(t("follow.follows_you"))}</span>` : ""}
              ${c.status === "failed" ? `<span class="chip failed" title="${esc(c.error || "")}">${esc(t("follow.status.failed"))}</span>` : ""}</div>
            <div class="fmatch"><span class="quiet">${esc(t("follow.source." + c.source))}</span> ${markWords((c.matched || c.bio || "").slice(0, 220), words)}</div>
            <div class="fstats">${followStats(c)}</div>
          </div>
          <div class="facts">
            <button class="pill small primary" data-a="follow">${esc(t("follow.follow"))}</button>
            <a class="link" href="https://x.com/${encodeURIComponent(c.handle)}" target="_blank" rel="noopener noreferrer">${esc(t("follow.profile"))} ↗</a>
            <button class="quiet" data-a="dismiss">${esc(t("follow.dismiss"))}</button>
          </div>
        </div>`);
      const cb = $("input[data-pick]", row);
      if (cb) cb.onchange = () => { cb.checked ? S_FOLLOW.picked.add(c.user_id) : S_FOLLOW.picked.delete(c.user_id); renderBatch(); };
      $('[data-a="follow"]', row).onclick = (e) => guard(e.currentTarget, async () => { await followOne(c, e.currentTarget); row.remove(); S_FOLLOW.picked.delete(c.user_id); renderBatch(); loadStatus(); });
      $('[data-a="dismiss"]', row).onclick = (e) => guard(e.currentTarget, async () => { await api("/api/follow/act", { ids: [c.user_id], action: "dismiss" }); row.remove(); S_FOLLOW.picked.delete(c.user_id); renderBatch(); });
      list.append(row);
    }
    if (r.eligible.length > SHOW) list.append(h(`<p class="sub" style="padding-top:10px">${esc(t("follow.more", { n: r.eligible.length - SHOW }))}</p>`));
    renderBatch();

    // excluded, with the reason
    const ex = h(`<details class="box fex"><summary><span>${esc(t("follow.excluded", { n: r.excluded.length }))}</span></summary><div></div></details>`);
    for (const c of r.excluded) {
      $("div", ex).append(h(`
        <div class="frow small">${avatar(c)}
          <div class="fbody"><div class="fname"><b>${esc(c.name)}</b> <span>@${esc(c.handle)}</span></div>
            <div class="fstats">${followStats(c)}</div></div>
          <span class="chip failed">${esc(t("follow.reason." + c.reason, { d: c.detail }))}</span>
        </div>`));
    }

    // followed / queued, and who followed back
    const done = h(`<details class="box fex" ${r.done.some((c) => c.status === "queued" || c.status === "opened") ? "open" : ""}><summary><span>${esc(t("follow.done", { n: r.done.length }))}</span></summary><div></div></details>`);
    for (const c of r.done) {
      const row = h(`
        <div class="frow small">${avatar(c)}
          <div class="fbody"><div class="fname"><b>${esc(c.name)}</b> <span>@${esc(c.handle)}</span>
            ${c.status === "followed" && c.followed_by ? `<span class="chip sent">${esc(t("follow.back"))}</span>` : ""}</div>
            <div class="fstats">${followStats(c)}${c.followed_at ? " · " + esc(since(c.followed_at)) : ""}</div></div>
          <span class="chip ${esc(c.status)}">${esc(t("follow.status." + c.status))}</span>
          <span class="facts"></span>
        </div>`);
      const acts = $(".facts", row);
      const act = (label, action) => { const b = h(`<button class="link">${esc(label)}</button>`); b.onclick = () => guard(b, async () => { await api("/api/follow/act", { ids: [c.user_id], action }); views.follow.load(); }); acts.append(b); };
      if (c.status === "queued") act(t("follow.cancel"), "cancel");
      if (c.status === "opened") { act(t("follow.confirm"), "followed"); act(t("follow.not_followed"), "restore"); }
      $("div", done).append(row);
    }

    const parts = [head];
    if (!r.eligible.length && !r.excluded.length && !r.done.length) parts.push(h(`<div class="empty">${esc(t("follow.empty"))}</div>`));
    else {
      parts.push(h(`<h2>${esc(t("follow.candidates"))}</h2>`));
      parts.push(r.eligible.length ? batch : h(`<p class="sub">${esc(t("follow.none_eligible"))}</p>`), list, ex, done);
    }
    main.replaceChildren(...parts);
  },
};

/* Compose + drafts */
views.compose = {
  action: () => ({ text: S.status?.drafting ? t("status.drafting") + "…" : t("action.more_drafts"), disabled: S.status?.drafting }),
  async onAction() { await api("/api/drafts/generate", {}); loadStatus(); },
  async load() {
    const r = await api("/api/drafts");
    const main = $("#view");
    const composer = editor({ kind: "post", text: sessionStorage.getItem("compose") || "" });
    $('[data-do="drop"]', composer).remove();
    $("textarea", composer).placeholder = t("compose.placeholder");
    $("textarea", composer).classList.add("tall");
    $("textarea", composer).addEventListener("input", (e) => { try { sessionStorage.setItem("compose", e.target.value); } catch {} });
    composer.addEventListener("click", (e) => { if (e.target.dataset.do === "send") try { sessionStorage.removeItem("compose"); } catch {} });
    const idea = h(`
      <div class="field" style="grid-template-columns:1fr auto;margin-top:6px">
        <input type="text" placeholder="${esc(t("compose.idea_ph"))}"><button class="pill">${esc(t("compose.idea_go"))}</button>
      </div>`);
    const list = h(`<div></div>`);
    $("button", idea).addEventListener("click", (e) => guard(e.currentTarget, async () => {
      const topic = $("input", idea).value.trim();
      if (!topic) return;
      const res = await api("/api/post/generate", { topic });
      if (!res.draft) return toast(t("draft.skipped"));
      list.prepend(editor(res.draft)); $("input", idea).value = "";
    }));
    for (const d of r.items) list.append(editor(d));
    main.replaceChildren(
      h(`<h2>${esc(t("compose.write"))}</h2>`), composer, idea,
      h(`<h2>${esc(t("compose.drafts"))}</h2>`),
      r.items.length ? h(`<p class="sub">${esc(t("compose.drafts_sub"))}</p>`) : h(`<div class="empty" style="padding:24px 0">${esc(t("compose.empty"))}</div>`),
      list);
  },
};

/* Outbox */
views.queue = {
  async load() {
    const r = await api("/api/outbox");
    const q = r.queue;
    const main = $("#view");
    const blocked = q.blocked ? t("queue.blocked." + q.blocked, { s: q.wait_sec }) : "";
    const head = h(`<p class="sub">${esc(t("queue.summary", { h: q.sent_hour, mh: q.max_hour, d: q.sent_day, md: q.max_day }))}${blocked ? " · " + esc(blocked) : ""}</p>`);
    if (!r.items.length) { main.replaceChildren(head, h(`<div class="empty">${esc(t("queue.empty"))}</div>`)); return; }
    const list = h(`<div class="list"></div>`);
    for (const it of r.items) {
      const link = it.result_id ? `https://x.com/i/status/${encodeURIComponent(it.result_id)}` : null;
      const row = h(`
        <div class="item"><div class="body">
          <div class="small"><span class="chip ${esc(it.status)}">${esc(t("queue.status." + it.status))}</span> · ${esc(t("kind." + it.kind))} · ${esc(t("channel.short." + it.channel))} · ${esc(ago(it.sent_at || it.created_at))}</div>
          ${it.target_author ? `<div class="small">${esc(t("queue.to"))} @${esc(it.target_author)}: ${esc((it.target_text || "").slice(0, 90))}</div>` : ""}
          <div class="title" style="font-weight:400;white-space:pre-wrap">${esc(it.text)}</div>
          ${it.error ? `<div class="small bad">${esc(it.error)}</div>` : ""}
          <div class="foot"></div>
        </div></div>`);
      const foot = $(".foot", row);
      const btn = (label, action, cls = "") => { const b = h(`<button class="${cls}">${esc(label)}</button>`); b.onclick = () => guard(b, async () => { await api("/api/outbox/act", { id: it.id, action }); views.queue.load(); loadStatus(); }); foot.append(b); };
      if (link) foot.append(h(`<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(t("queue.view"))} ↗</a>`));
      if (it.status === "opened") {
        const again = h(`<button>${esc(t("queue.reopen"))}</button>`);
        again.onclick = () => { if (it.kind === "quote") copy(it.text); window.open(intentUrl(it), "_blank", "noopener"); };
        foot.append(again);
        btn(t("queue.confirm"), "confirm", "go"); btn(t("queue.not_sent"), "not_sent");
      }
      if (it.status === "pending") btn(t("queue.cancel"), "cancel");
      if (it.status === "failed") btn(t("queue.retry"), "retry");
      list.append(row);
    }
    main.replaceChildren(head, list);
  },
};
function intentUrl(it) {
  if (it.kind === "quote" && it.target_url) return it.target_url;  // quote: open the post, Repost > Quote
  const p = new URLSearchParams({ text: it.text });
  if (it.kind === "reply" && it.target_id) p.set("in_reply_to", it.target_id);
  if (it.kind === "quote" && it.target_url) p.set("url", it.target_url);
  return "https://x.com/intent/post?" + p;
}

/* Learning */
views.learn = {
  async load() {
    const r = await api("/api/learn");
    const main = $("#view");
    const mine = r.mine || { total: 0, by: [] };
    const bySrc = {};
    for (const b of mine.by) bySrc[b.origin] = (bySrc[b.origin] || 0) + b.n;
    const lastEval = r.evals.find((x) => x.label === "current" || x.label === "candidate");
    const tiles = h(`
      <div class="tiles">
        <div class="tile"><div class="n">${mine.total}</div><div class="l">${esc(t("learn.my_posts"))}</div></div>
        <div class="tile"><div class="n">${r.examples}</div><div class="l">${esc(t("learn.examples"))}</div></div>
        <div class="tile"><div class="n">${r.edits}</div><div class="l">${esc(t("learn.edits"))}</div></div>
        <div class="tile"><div class="n">${lastEval ? Number(lastEval.score).toFixed(1) : "—"}</div><div class="l">${esc(t("learn.fit_eval"))}</div></div>
        <div class="tile"><div class="n">${r.fit.n ? ((r.fit.a + r.fit.b) / 2).toFixed(1) : "—"}</div><div class="l">${esc(t("learn.fit_live", { n: r.fit.n }))}</div></div>
      </div>`);
    const src = Object.entries(bySrc).map(([k, n]) => `${t("origin." + k)} ${n}`).join(" · ");
    const running = r.state.learning ? t("learn.task." + r.state.task) : "";
    const acts = h(`
      <div>
        <p class="sub" style="margin-top:10px">${esc(src || t("learn.no_posts"))}${running ? ` · <span class="warn spin">${esc(running)}</span>` : ""}</p>
        <div class="actions">
          <button class="pill" data-t="scrape_mine">${esc(t("learn.scrape"))}</button>
          <label class="pill" style="cursor:pointer">${esc(t("learn.import"))}<input type="file" accept=".zip,.js,application/zip,text/javascript" hidden></label>
          <button class="pill" data-t="consolidate">${esc(t("learn.consolidate"))}</button>
          <button class="pill" data-t="eval">${esc(t("learn.eval"))}</button>
        </div>
        <p class="sub" style="margin-top:10px">${esc(t("learn.explain", { days: r.next_consolidate_days, n: r.eval_sample }))}</p>
      </div>`);
    $$("[data-t]", acts).forEach((b) => { b.disabled = r.state.learning; b.onclick = () => guard(b, async () => {
      const res = await api("/api/learn/run", { task: b.dataset.t, force: b.dataset.t === "consolidate" });
      toast(res.started ? t("learn.started") : t("learn.busy")); loadStatus(); setTimeout(() => views.learn.load(), 600);
    }); });
    $("input[type=file]", acts).addEventListener("change", async (e) => {
      const f = e.target.files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      toast(t("learn.importing"));
      try { const res = await api("/api/import/archive", fd); toast(t("learn.imported", res)); views.learn.load(); }
      catch (err) { toast(err.message, "err"); }
      e.target.value = "";
    });

    const chart = h(`<div class="chart"><div class="legend"><span><i style="background:var(--violet)"></i>${esc(t("learn.line.current"))}</span><span><i style="background:var(--pink)"></i>${esc(t("learn.line.candidate"))}</span><span><i style="background:var(--faint)"></i>${esc(t("learn.line.baseline"))}</span></div>${fitChart(r.evals)}</div>`);

    const files = h(`<div></div>`);
    for (const name of ["persona.md", "work.md", "style_notes.md"]) {
      const box = h(`
        <details class="box" ${name === "persona.md" && !r.filled[name] ? "open" : ""}>
          <summary><span>${esc(t("file." + name))} <span class="${r.filled[name] ? "ok" : "warn"}" style="font-weight:400;font-size:12.5px">${esc(r.filled[name] ? t("file.filled") : t("file.empty"))}</span></span></summary>
          <p class="sub" style="margin:8px 0 0">${esc(t("file." + name + ".help"))}</p>
          <textarea spellcheck="false"></textarea>
          <div class="row"><span class="quiet"></span><button class="pill primary small">${esc(t("common.save"))}</button></div>
        </details>`);
      $("textarea", box).value = r.files[name] || "";
      $("button", box).onclick = (e) => guard(e.currentTarget, async () => {
        const res = await api("/api/profile", { name, text: $("textarea", box).value });
        toast(t("common.saved")); $(".quiet", box).textContent = res.filled ? "" : t("file.still_empty");
      });
      files.append(box);
    }

    const versions = h(`<table><thead><tr><th>${esc(t("learn.v.time"))}</th><th>${esc(t("learn.v.reason"))}</th><th>${esc(t("learn.v.score"))}</th><th></th></tr></thead><tbody></tbody></table>`);
    for (const v of r.versions) {
      const tr = h(`<tr><td>${esc(ago(v.created_at))}</td><td>${esc(t("learn.reason." + v.reason))}</td><td class="num">${v.score != null ? Number(v.score).toFixed(2) : "—"}</td><td style="text-align:right"></td></tr>`);
      tr.title = v.preview;
      if (v.active) tr.lastChild.append(h(`<span class="chip sent">${esc(t("learn.v.active"))}</span>`));
      else { const b = h(`<button class="link">${esc(t("learn.v.use"))}</button>`); b.onclick = () => guard(b, async () => { await api("/api/learn/activate", { id: v.id }); toast(t("common.saved")); views.learn.load(); }); tr.lastChild.append(b); }
      $("tbody", versions).append(tr);
    }
    const evals = h(`<table><thead><tr><th>${esc(t("learn.v.time"))}</th><th>${esc(t("learn.e.label"))}</th><th>A</th><th>B</th><th>${esc(t("learn.e.n"))}</th><th></th></tr></thead><tbody></tbody></table>`);
    for (const x of r.evals.slice(0, 12)) {
      const tr = h(`<tr><td>${esc(ago(x.ts))}</td><td>${esc(t("learn.line." + x.label))}</td><td class="num">${x.score_a ?? "—"}</td><td class="num">${x.score_b ?? "—"}</td><td class="num">${x.n}</td><td style="text-align:right"><button class="link">${esc(t("learn.e.detail"))}</button></td></tr>`);
      $("button", tr).onclick = () => showEval(x.id);
      $("tbody", evals).append(tr);
    }
    main.replaceChildren(
      h(`<h2>${esc(t("learn.overview"))}</h2>`), tiles, acts,
      h(`<h2>${esc(t("learn.chart"))}</h2>`), chart,
      h(`<h2>${esc(t("learn.profile"))}</h2>`), files,
      h(`<h2>${esc(t("learn.versions"))}</h2>`), r.versions.length ? versions : h(`<p class="sub">${esc(t("learn.no_versions"))}</p>`),
      h(`<h2>${esc(t("learn.evals"))}</h2>`), r.evals.length ? evals : h(`<p class="sub">${esc(t("learn.no_evals"))}</p>`));
  },
};

function fitChart(evals) {
  const pts = evals.filter((e) => e.score != null).slice().reverse();
  if (pts.length < 1) return `<p class="sub" style="padding:30px 0;text-align:center">${esc(t("learn.no_evals"))}</p>`;
  const W = 640, H = 160, pad = 26;
  // x = which evaluation run; evaluations within 10 minutes of each other are one run
  const runOf = (p) => Math.floor(new Date(p.ts).getTime() / 600000);
  const runs = [...new Set(pts.map(runOf))].sort((a, b) => a - b);
  const X = (p) => pad + (runs.length === 1 ? (W - 2 * pad) / 2 : (runs.indexOf(runOf(p)) / (runs.length - 1)) * (W - 2 * pad));
  const lo = Math.max(0, Math.floor(Math.min(...pts.map((p) => p.score))) - 1);  // zoom in on the range that's used
  const Y = (s) => H - pad - ((s - lo) / (10 - lo)) * (H - 2 * pad);
  const colors = { current: "var(--violet)", candidate: "var(--pink)", baseline: "var(--faint)" };
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(t("learn.chart"))}">`;
  for (const g of [2, 4, 6, 8, 10].filter((g) => g >= lo)) svg += `<line x1="${pad}" x2="${W - pad}" y1="${Y(g)}" y2="${Y(g)}" stroke="var(--line)"/><text x="4" y="${Y(g) + 4}" font-size="10" fill="var(--muted)">${g}</text>`;
  for (const [label, color] of Object.entries(colors)) {
    const series = pts.filter((p) => p.label === label);
    if (!series.length) continue;
    const d = series.map((p, i) => `${i ? "L" : "M"}${X(p).toFixed(1)},${Y(p.score).toFixed(1)}`).join(" ");
    svg += `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" ${label === "candidate" ? 'stroke-dasharray="4 4"' : ""}/>`;
    for (const p of series) svg += `<circle cx="${X(p).toFixed(1)}" cy="${Y(p.score).toFixed(1)}" r="3" fill="${color}"><title>${esc(t("learn.line." + label))} ${p.score} · ${new Date(p.ts).toLocaleString()}</title></circle>`;
  }
  return svg + "</svg>";
}

async function showEval(id) {
  const d = await api(`/api/learn/eval/${id}`);
  const body = $("#modal .modal-body");
  body.replaceChildren(h(`<h3 style="margin-top:0">${esc(t("learn.line." + d.label))} · A ${d.score_a} · B ${d.score_b}</h3>`));
  for (const x of d.detail) body.append(h(`
    <div class="pair">
      <div class="quiet">${esc(x.post)}</div>
      <div><b>${esc(t("learn.e.real"))}</b> ${esc(x.real)}</div>
      <div><b>A ${esc(x.score_a)}</b> ${esc(x.a)}</div>
      <div><b>B ${esc(x.score_b)}</b> ${esc(x.b)}</div>
      <div class="quiet">${esc(x.why || "")}</div>
    </div>`));
  $("#modal").showModal();
}

/* Settings */
const AI_PRESETS = [
  ["openai", "https://api.openai.com/v1", "gpt-5.6-mini"],
  ["anthropic", "https://api.anthropic.com/v1", "claude-sonnet-5"],
  ["openrouter", "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-5"],
  ["deepseek", "https://api.deepseek.com/v1", "deepseek-chat"],
  ["ollama", "http://localhost:11434/v1", "qwen3:14b"],
];
const SECTIONS = [
  ["x", ["MY_HANDLE", "DISPLAY_NAME"]],
  ["ai", ["AI_BASE_URL", "AI_API_KEY", "AI_MODEL"]],
  ["post", ["POST_CHANNEL", "SEND_MIN_INTERVAL_SEC", "SEND_MAX_PER_HOUR", "SEND_MAX_PER_DAY", "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]],
  ["radar", ["AUTO_REFRESH", "REFRESH_MIN_MINUTES", "REFRESH_MAX_MINUTES", "SHOW_TOP", "SCRAPE_TARGET", "RECHECK_TOP", "TRENDS_EVERY_MINUTES", "WATCH_EVERY_MINUTES", "KEEP_DAYS"]],
  ["learn", ["FIT_REVIEW", "FIT_MIN_SCORE", "CONSOLIDATE_EVERY_DAYS", "EVAL_SAMPLES", "MINE_REFRESH_HOURS", "MINE_SCROLLS"]],
  ["drafts", ["DRAFT_HOUR", "NEWS_PER_DAY", "QUOTE_MIN_SCORE"]],
  ["follow", ["FOLLOW_KEYWORDS", "FOLLOW_MAX_RATIO", "FOLLOW_MIN_FOLLOWING", "FOLLOW_MIN_POSTS", "FOLLOW_SEARCH_SCROLLS", "FOLLOW_MIN_INTERVAL_SEC", "FOLLOW_MAX_PER_HOUR", "FOLLOW_MAX_PER_DAY"]],
  ["general", ["UI_LANG", "CONTENT_LANG"]],
  ["mutes", []],
];
const PAIRS = { REFRESH_MIN_MINUTES: "REFRESH_MAX_MINUTES" };  // one row: "6 – 10 minutes"
const UNITS = {
  SEND_MIN_INTERVAL_SEC: "sec", SEND_MAX_PER_HOUR: "posts", SEND_MAX_PER_DAY: "posts", REFRESH_MIN_MINUTES: "min",
  SHOW_TOP: "posts", SCRAPE_TARGET: "posts", RECHECK_TOP: "posts", TRENDS_EVERY_MINUTES: "min", WATCH_EVERY_MINUTES: "min",
  KEEP_DAYS: "day", CONSOLIDATE_EVERY_DAYS: "day", EVAL_SAMPLES: "posts", MINE_REFRESH_HOURS: "hour", MINE_SCROLLS: "screens",
  DRAFT_HOUR: "oclock", NEWS_PER_DAY: "posts", FIT_MIN_SCORE: "points", QUOTE_MIN_SCORE: "points",
  FOLLOW_MAX_RATIO: "times", FOLLOW_MIN_FOLLOWING: "people", FOLLOW_MIN_POSTS: "posts", FOLLOW_SEARCH_SCROLLS: "screens",
  FOLLOW_MIN_INTERVAL_SEC: "sec", FOLLOW_MAX_PER_HOUR: "people", FOLLOW_MAX_PER_DAY: "people",
};
const HIDDEN_IN_PAIR = new Set(Object.values(PAIRS));

function control(key, meta, vals) {
  const id = "f_" + key;
  if (meta.kind === "bool") return `<label class="switch"><input id="${id}" type="checkbox" ${meta.value === "1" ? "checked" : ""}><span></span></label>`;
  if (key === "POST_CHANNEL") return `<div class="choices">${meta.choices.map((c) => `<label class="choice"><input type="radio" name="${id}" value="${c}" ${meta.value === c ? "checked" : ""}><div><b>${esc(t("channel." + c))}</b><span>${esc(t("channel." + c + ".help"))}</span></div></label>`).join("")}</div>`;
  if (meta.kind === "choice") return `<select id="${id}">${meta.choices.map((c) => `<option value="${c}" ${meta.value === c ? "selected" : ""}>${esc(t("choice." + key + "." + c))}</option>`).join("")}</select>`;
  if (meta.kind === "secret") return `<input id="${id}" type="password" autocomplete="off" placeholder="${esc(meta.set ? t("set.secret_set", { hint: meta.hint }) : t("set.secret_empty"))}">`;
  if (meta.kind === "int" || meta.kind === "float") {
    const box = (k, m) => `<input id="f_${k}" type="number" class="short" ${m.kind === "float" ? 'step="0.5"' : 'step="1"'} value="${esc(m.value)}">`;
    const unit = UNITS[key] ? `<em>${esc(t("unit." + UNITS[key]))}</em>` : "";
    const pair = PAIRS[key] && vals[PAIRS[key]] ? `<span class="dash">–</span>${box(PAIRS[key], vals[PAIRS[key]])}` : "";
    return `<span class="num">${box(key, meta)}${pair}${unit}</span>`;
  }
  return `<input id="${id}" type="text" value="${esc(meta.value)}">`;
}
function settingRow(key, meta, vals) {
  const label = PAIRS[key] ? t("set." + key + ".pair") : t("set." + key);
  const help = I18N[S.lang]["set." + key + ".help"] ? `<p>${t("set." + key + ".help")}</p>` : "";
  const wide = key === "POST_CHANNEL" ? " wide" : "";
  return `<div class="srow${wide}" data-key="${key}"><div class="slabel"><label for="f_${key}">${esc(label)}</label>${help}</div><div class="sctl">${control(key, meta, vals)}</div></div>`;
}
function readField(box, key, meta) {
  const id = "f_" + key;
  if (meta.kind === "bool") return $("#" + id, box).checked ? "1" : "0";
  if (key === "POST_CHANNEL") return ($(`input[name="${id}"]:checked`, box) || {}).value || meta.value;
  return $("#" + id, box).value;
}

let settingsSection = "x";
try { settingsSection = localStorage.getItem("settingsSection") || "x"; } catch {}

views.settings = {
  async load() {
    const r = await api("/api/settings");
    const vals = r.values, st = r.setup;
    const main = $("#view");
    const dot = { x: st.x && !st.login_expired ? "ok" : st.x ? "bad" : "warn", ai: st.ai ? "ok" : "warn",
                  post: vals.POST_CHANNEL.value === "api" && !vals.X_API_KEY.set ? "warn" : "" };
    const steps = [["x", st.x && !st.login_expired, "x"], ["ai", st.ai, "ai"], ["handle", st.handle, "x"],
                   ["persona", st.persona, "learn"], ["mine", st.mine > 0, "learn"]];
    const todo = steps.filter(([, ok]) => !ok);
    const setup = todo.length ? h(`<div class="setup"><b>${esc(t("setup.title"))}</b>${steps.map(([k, ok, go]) => `<button class="${ok ? "is-done" : ""}" data-jump="${go}" ${ok ? "disabled" : ""}><span>${ok ? "✓" : "○"}</span>${esc(t("setup." + k))}</button>`).join("")}</div>`) : null;
    const nav = h(`<nav class="snav" aria-label="${esc(t("settings.title"))}">${SECTIONS.map(([sec]) => `<button data-sec="${sec}"><span>${esc(t("sec." + sec))}</span>${dot[sec] ? `<i class="st ${dot[sec]}"></i>` : ""}</button>`).join("")}</nav>`);
    const holder = h(`<div class="spanel"></div>`);
    const show = async (sec) => {
      if (!SECTIONS.some(([s]) => s === sec)) sec = "x";
      settingsSection = sec;
      try { localStorage.setItem("settingsSection", sec); } catch {}
      $$("button", nav).forEach((b) => b.setAttribute("aria-current", b.dataset.sec === sec));
      holder.replaceChildren(await settingsPanel(sec, vals, st));
    };
    $$("button", nav).forEach((b) => (b.onclick = () => show(b.dataset.sec)));
    if (setup) $$("[data-jump]", setup).forEach((b) => (b.onclick = () => (b.dataset.jump === "learn" ? setView("learn") : show(b.dataset.jump))));
    main.replaceChildren(...[setup, h(`<div class="settings"></div>`)].filter(Boolean));
    $(".settings", main).append(nav, holder);
    await show(settingsSection);
  },
};

async function settingsPanel(sec, vals, st) {
  const keys = SECTIONS.find(([s]) => s === sec)[1];
  const panel = h(`<section class="panel"><header><h3>${esc(t("sec." + sec))}</h3><p class="sub">${esc(t("sec." + sec + ".desc"))}</p></header></section>`);
  if (sec === "mutes") {
    const mutes = await api("/api/mutes");
    if (!mutes.items.length) panel.append(h(`<p class="sub">${esc(t("mutes.empty"))}</p>`));
    for (const m of mutes.items) {
      const row = h(`<div class="srow"><div class="slabel"><label>${esc(m.value)}</label><p>${esc(t("mutes." + m.kind))}</p></div><div class="sctl right"><button class="pill small">${esc(t("mutes.remove"))}</button></div></div>`);
      $("button", row).onclick = (e) => guard(e.currentTarget, async () => { await api("/api/feedback", { kind: "unmute_" + m.kind, value: m.value }); row.remove(); });
      panel.append(row);
    }
    return panel;
  }
  if (sec === "x") panel.append(xAccountBlock(st));
  if (sec === "ai") {
    panel.append(h(`<div class="srow"><div class="slabel"><label for="preset">${esc(t("set.preset"))}</label></div><div class="sctl"><select id="preset"><option value="">${esc(t("set.preset_pick"))}</option>${AI_PRESETS.map(([n]) => `<option value="${n}">${esc(t("preset." + n))}</option>`).join("")}</select></div></div>`));
  }
  for (const k of keys) if (vals[k] && !HIDDEN_IN_PAIR.has(k)) panel.insertAdjacentHTML("beforeend", settingRow(k, vals[k], vals));
  const foot = h(`<footer><span class="result"></span>${sec === "ai" ? `<button class="pill" data-test="ai">${esc(t("set.test"))}</button>` : ""}${sec === "post" ? `<button class="pill" data-test="api">${esc(t("set.test_api"))}</button>` : ""}<button class="pill primary" data-save>${esc(t("common.save"))}</button></footer>`);
  panel.append(foot, h(`<p class="note">${esc(t("settings.local"))}</p>`));

  const preset = $("#preset", panel);
  if (preset) preset.onchange = () => {
    const p = AI_PRESETS.find((x) => x[0] === preset.value);
    if (!p) return;
    $("#f_AI_BASE_URL", panel).value = p[1];
    if (!$("#f_AI_MODEL", panel).value) $("#f_AI_MODEL", panel).value = p[2];
  };
  if (sec === "post") {
    const toggleApi = () => {
      const api_ = readField(panel, "POST_CHANNEL", vals.POST_CHANNEL) === "api";
      $$('[data-key^="X_A"]', panel).forEach((f) => (f.hidden = !api_));
      $('[data-test="api"]', panel).hidden = !api_;
    };
    $$('input[name="f_POST_CHANNEL"]', panel).forEach((i) => (i.onchange = toggleApi));
    toggleApi();
  }
  $("[data-save]", foot).onclick = (e) => guard(e.currentTarget, async () => {
    const values = {};
    for (const k of keys) if (vals[k]) values[k] = readField(panel, k, vals[k]);
    await api("/api/settings", { values });
    toast(t("common.saved"));
    if ("UI_LANG" in values) await applyLang();
    await loadStatus();
    views.settings.load();
  });
  $$("[data-test]", foot).forEach((b) => (b.onclick = () => guard(b, async () => {
    const res = await api("/api/settings/test", { what: b.dataset.test });
    const out = $(".result", foot);
    out.className = "result " + (res.ok ? "ok" : "bad");
    out.textContent = (res.ok ? "✓ " : "✗ ") + (I18N[S.lang]["err." + res.detail] ? t("err." + res.detail) : res.detail || "");
  })));
  return panel;
}

function xAccountBlock(st) {
  const state = st.x ? (st.login_expired ? "bad" : "ok") : "warn";
  const label = st.x ? (st.login_expired ? t("x.expired") : t("x.saved_as", { handle: S.status?.handle ? "@" + S.status.handle : "" })) : t("x.none");
  const el = h(`
    <div class="xacct">
      <div class="xstate"><i class="st ${state}"></i><span>${esc(label)}</span><span class="result"></span>
        <span class="acts">${st.x ? `<button class="quiet" data-x="logout">${esc(t("x.logout"))}</button><button class="pill small" data-x="test">${esc(t("x.test"))}</button><button class="pill small" data-x="toggle">${esc(t("x.update"))}</button>` : ""}</span>
      </div>
      <div class="xpaste" ${st.x && !st.login_expired ? "hidden" : ""}>
        <details class="howto" ${st.x ? "" : "open"}><summary>${esc(t("x.howto"))}</summary>${t("x.howto_body")}</details>
        <textarea rows="2" placeholder="${esc(t("x.paste_ph"))}" spellcheck="false"></textarea>
        <div class="right"><button class="pill primary small" data-x="save">${esc(t("x.save"))}</button></div>
      </div>
    </div>`);
  const out = $(".result", el);
  const show = (res) => {
    out.className = "result " + (res.ok ? "ok" : "bad");
    out.textContent = res.ok ? t("x.ok", { handle: res.detail }) : (I18N[S.lang]["err." + res.detail] ? t("err." + res.detail) : res.detail);
  };
  $('[data-x="save"]', el).onclick = (e) => guard(e.currentTarget, async () => {
    await api("/api/settings/cookie", { text: $("textarea", el).value });
    $("textarea", el).value = "";
    out.className = "result"; out.textContent = t("x.testing");
    show(await api("/api/settings/test", { what: "x" }));
    await loadStatus();
    setTimeout(() => views.settings.load(), 1200);
  });
  const test = $('[data-x="test"]', el);
  if (test) test.onclick = () => guard(test, async () => { out.className = "result"; out.textContent = t("x.testing"); show(await api("/api/settings/test", { what: "x" })); loadStatus(); });
  const toggle = $('[data-x="toggle"]', el);
  if (toggle) toggle.onclick = () => { const p = $(".xpaste", el); p.hidden = !p.hidden; if (!p.hidden) $("textarea", el).focus(); };
  const lo = $('[data-x="logout"]', el);
  if (lo) lo.onclick = () => guard(lo, async () => { if (!confirm(t("x.logout_confirm"))) return; await api("/api/settings/logout-x", {}); views.settings.load(); loadStatus(); });
  return el;
}

// ---------- navigation ----------

const TABS = ["radar", "trends", "news", "follow", "compose", "queue", "learn", "settings"];

function renderTabs() {
  $("#tabs").replaceChildren(...TABS.map((v) => {
    const b = h(`<button class="tab" role="tab" data-view="${v}" aria-selected="${v === S.view}">${esc(t("nav." + v))}${v === "queue" ? '<span class="dot" hidden></span>' : ""}</button>`);
    b.onclick = () => setView(v);
    return b;
  }));
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
}

async function setView(v) {
  if (!views[v]) v = "radar";
  S.view = v;
  try { localStorage.setItem("view", v); } catch {}
  if (location.hash !== "#" + v) history.replaceState(null, "", "#" + v);
  $$(".tab").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === v));
  $("#batch").hidden = true;
  renderStatus();
  $("#view").replaceChildren(h(`<div class="empty spin">${esc(t("common.loading"))}</div>`));
  try { await views[v].load(); } catch (e) { $("#view").replaceChildren(h(`<div class="empty bad">${esc(e.message)}</div>`)); }
  renderBatch();
}

async function applyLang() {
  let pref = "auto";
  try { pref = (await api("/api/settings")).values.UI_LANG.value; } catch {}
  S.lang = pref === "zh" || pref === "en" ? pref : ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en");
  document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en";
  renderTabs();
}

document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (go) setView(go.dataset.go);
});
$("#action").addEventListener("click", (e) => { const v = views[S.view]; if (v.onAction) guard(e.currentTarget, () => v.onAction()); });
window.addEventListener("hashchange", () => { const v = location.hash.slice(1); if (v && v !== S.view && views[v]) setView(v); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadStatus(); });

(async function start() {
  await applyLang();
  let first = location.hash.slice(1);
  if (!views[first]) { try { first = localStorage.getItem("view") || "radar"; } catch { first = "radar"; } }
  await loadStatus();
  if (S.status && !S.status.x_ready && !S.status.ai_ready) first = "settings";
  setView(first);
})();
