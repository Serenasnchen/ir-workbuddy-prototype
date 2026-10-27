/* Core runtime: tabs, evidence drawer, source lookup, tiny SVG chart helpers. No external deps. */
(function () {
  "use strict";
  const D = window.DATA || {};
  const EV = [];            // evidence registry: index -> {title, value, label, src:[ids], quote, note, module}
  const SRC = {};           // global source registry: "module:id" and plain id fallbacks

  // Merge every module's sources into one lookup. Ids are namespaced by module to avoid collisions.
  Object.keys(D).forEach((m) => {
    const mod = D[m];
    if (!mod || !Array.isArray(mod.sources)) return;
    mod.sources.forEach((s) => {
      SRC[m + ":" + s.id] = s;
      if (!SRC[s.id]) SRC[s.id] = s;
    });
  });

  const LABEL_CLASS = { "公开披露": "public", "结构化数据": "data", "计算": "calc", "推断": "infer" };
  const TIER_TEXT = {
    1: "一级：公司公告 / 港交所 / SEC 文件",
    2: "二级：官方 webcast / 官方新闻稿",
    3: "三级：第三方文字稿（非官方逐字稿）",
    4: "四级：媒体或券商观点转述（二手）",
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function labelTag(label) {
    if (!label) return "";
    return `<span class="tag ${LABEL_CLASS[label] || ""}">${esc(label)}</span>`;
  }

  // Register a piece of evidence and return the clickable HTML for it.
  function ev(text, info) {
    const i = EV.push(info || {}) - 1;
    return `<span class="ev" tabindex="0" role="button" data-ev="${i}">${esc(text)}</span>`;
  }

  function resolveSources(module, ids) {
    return (ids || []).map((id) => SRC[module + ":" + id] || SRC[id] || { id, title: "（来源编号 " + id + "）", url: "" });
  }

  const drawer = () => document.getElementById("drawer");

  function openEvidence(i, el) {
    const e = EV[i];
    if (!e) return;
    document.querySelectorAll(".ev.on").forEach((x) => x.classList.remove("on"));
    if (el) el.classList.add("on");
    const srcs = resolveSources(e.module, e.src);
    const srcHtml = srcs.length
      ? srcs.map((s) => `<div style="margin-bottom:8px">${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>` : esc(s.title)}`
          + `<div style="color:var(--muted)">${esc(s.date || "")}${s.tier ? "｜" + esc(TIER_TEXT[s.tier] || "层级 " + s.tier) : ""}</div></div>`).join("")
      : `<span style="color:var(--muted)">本条为页面内计算或汇总，见下方说明</span>`;
    const d = drawer();
    d.querySelector("h4").textContent = e.title || "证据";
    d.querySelector(".body").innerHTML =
      (e.value ? `<div class="value">${esc(e.value)}</div>` : "") +
      `<div style="margin-bottom:12px">${labelTag(e.label)}${e.status ? `<span class="tag ${/核实|一致|confirmed/.test(e.status) ? "ok" : "infer"}">${esc(e.status)}</span>` : ""}</div>` +
      (e.quote ? `<blockquote>${esc(e.quote)}</blockquote>` : "") +
      `<dl><dt>来源</dt><dd>${srcHtml}</dd>` +
      (e.note ? `<dt>说明</dt><dd>${esc(e.note)}</dd>` : "") +
      (e.module ? `<dt>产物</dt><dd>${esc(moduleKind(e.module))}</dd>` : "") +
      `</dl>`;
    d.classList.add("open");
    d.setAttribute("aria-hidden", "false");
  }

  function moduleKind(m) {
    const mod = D[m];
    if (!mod || !mod.meta) return "";
    return `${mod.meta.generated_by || ""}｜${mod.meta.script || ""}`;
  }

  function closeEvidence() {
    drawer().classList.remove("open");
    drawer().setAttribute("aria-hidden", "true");
    document.querySelectorAll(".ev.on").forEach((x) => x.classList.remove("on"));
  }

  document.addEventListener("click", (e) => {
    const t = e.target.closest(".ev");
    if (t) { openEvidence(+t.dataset.ev, t); return; }
    if (e.target.closest(".drawer .close")) closeEvidence();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeEvidence();
    const t = document.activeElement;
    if ((e.key === "Enter" || e.key === " ") && t && t.classList && t.classList.contains("ev")) {
      e.preventDefault(); openEvidence(+t.dataset.ev, t);
    }
    if (!/INPUT|TEXTAREA/.test((t && t.tagName) || "") && /^[1-6]$/.test(e.key)) selectTab(+e.key - 1);
  });

  // ---------- tabs ----------
  function selectTab(idx) {
    const tabs = [...document.querySelectorAll(".tab")];
    if (!tabs[idx]) return;
    tabs.forEach((t, i) => t.setAttribute("aria-selected", i === idx ? "true" : "false"));
    document.querySelectorAll(".panel").forEach((p, i) => p.classList.toggle("active", i === idx));
    const panel = document.querySelectorAll(".panel")[idx];
    const tr = document.getElementById("trace");
    if (tr && panel) tr.innerHTML = panel.dataset.trace || "";
    closeEvidence();
    window.scrollTo({ top: 0 });
    history.replaceState(null, "", "#" + (panel ? panel.id : ""));
  }

  // ---------- SVG helpers ----------
  const NS = "http://www.w3.org/2000/svg";
  function svg(w, h, inner) {
    return `<svg viewBox="0 0 ${w} ${h}" xmlns="${NS}" role="img" style="width:100%;height:auto;display:block">${inner}</svg>`;
  }
  function scale(d0, d1, r0, r1) {
    const k = (r1 - r0) / ((d1 - d0) || 1);
    return (v) => r0 + (v - d0) * k;
  }
  function fmt(n, digits) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("zh-CN", { maximumFractionDigits: digits == null ? 1 : digits, minimumFractionDigits: digits == null ? 0 : digits });
  }
  function dateNum(s) { return Date.parse(s + "T00:00:00Z") / 86400000; }

  window.IR = { D, ev, esc, labelTag, svg, scale, fmt, dateNum, selectTab, openEvidence, SRC, resolveSources };

  document.addEventListener("DOMContentLoaded", () => {
    (window.IR_RENDERERS || []).forEach((r) => {
      try { r(); } catch (err) {
        console.error("render failed:", r.name, err);
        const host = document.getElementById(r.panelId || "");
        if (host) host.insertAdjacentHTML("beforeend", `<p class="tag warn">本模块渲染失败：${esc(err.message)}</p>`);
      }
    });
    document.querySelectorAll(".tab").forEach((t, i) => t.addEventListener("click", () => selectTab(i)));
    const hash = location.hash.replace("#", "");
    const panels = [...document.querySelectorAll(".panel")];
    const idx = Math.max(0, panels.findIndex((p) => p.id === hash));
    selectTab(idx);
  });
})();
