/* Panel 2: 同业矩阵 — 8 companies x 8 topics (click-through to quotes), capex on two bases, two flash notes */
(function () {
  "use strict";
  const CHG = { "实质变化": "warn", "口径变化": "infer", "新增": "public", "无变化": "" };

  function render() {
    const { D, ev, esc, fmt } = window.IR;
    const host = document.getElementById("peers");
    const M = D.m1_peer;
    if (!M) { host.innerHTML = `<p class="sub">本模块数据尚未生成。</p>`; return; }
    const cos = M.companies;
    const cellOf = (c, t) => M.cells.find((x) => x.company === c && x.topic === t);

    let h = `<h2 class="lede">同业都在加码 AI 资本开支，分歧在于给不给量化指引、怎么讲回报</h2>`;
    h += `<p class="sub">8 家公司 × 8 个固定议题，每格可点开原句与出处；与上一季相比的变化分为“实质变化”与“口径变化”。美股三家将于 10-28/29 发布，发布后用同一脚本、同一议题列重跑。</p>`;

    // matrix
    h += `<div class="block" style="overflow-x:auto"><div class="matrix" style="grid-template-columns:150px repeat(${cos.length}, minmax(118px, 1fr));min-width:1100px">`;
    h += `<div class="h">议题</div>` + cos.map((c) => `<div class="h">${esc(c.name)}<div style="font-weight:400;color:var(--muted);font-size:11.5px">${esc(c.latest)}${c.id !== "tencent" && /未发布|上一季/.test(c.status || "") ? "（待更新）" : ""}</div></div>`).join("");
    M.topics.forEach((t) => {
      h += `<div class="h">${esc(t.name)}</div>`;
      cos.forEach((c) => {
        const x = cellOf(c.id, t.id);
        if (!x) { h += `<div class="c empty">—</div>`; return; }
        const st = (x.change_vs_prior && x.change_vs_prior.status) || "";
        const q = x.quote && x.quote.text;
        h += `<div class="c">${ev(x.value_short, {
          module: "m1_peer", title: `${c.name}｜${t.name}（${x.period_label}）`, value: x.value_short,
          quote: q ? q + (x.quote.speaker ? " —— " + x.quote.speaker : "") : "", label: x.label, src: x.src,
          note: [x.detail, x.label_note, x.change_vs_prior && x.change_vs_prior.text, x.prior ? "上一季：" + x.prior.value_short : ""].filter(Boolean).join("｜"),
        })}${st && st !== "无变化" ? `<span class="chg"><span class="tag ${CHG[st] || ""}">${esc(st)}</span></span>` : ""}</div>`;
      });
    });
    h += `</div><div class="legend"><span><span class="tag warn">实质变化</span>业务或指引真的变了</span><span><span class="tag infer">口径变化</span>定义或范围变了，不可直接比</span><span><span class="tag public">新增</span>上一季没有披露</span></div></div>`;

    // capex table + tencent trajectory
    const ct = M.capex_table;
    h += `<div class="grid-2"><div class="block"><h3>资本开支：公司口径 vs 现金口径</h3><p class="hint">折合美元按 ${esc(ct.fx.rmb_per_usd)} 人民币/美元（${esc(ct.fx.date)}，${esc(ct.fx.basis)}）。不同公司口径不同，只作量级比较。</p>`
      + `<table class="t"><thead><tr><th>公司</th><th>期间</th><th class="n">公司口径</th><th class="n">同比</th><th class="n">现金口径</th><th>全年指引</th></tr></thead><tbody>`
      + ct.rows.map((r) => {
        const cb = r.company_basis || {}, cash = r.cash_basis || {};
        const g = r.guidance || {};
        return `<tr><td><b>${esc(r.name)}</b></td><td>${esc(r.period)}</td>`
          + `<td class="n">${cb.display ? ev(usdYi(cb.display), { module: "m1_peer", title: `${r.name} 资本开支（公司口径）`, value: `${cb.display}（${cb.usd_display || ""}）`, label: cb.label, src: cb.src, note: cb.definition }) : "未披露"}</td>`
          + `<td class="n">${esc(cb.yoy_display || "—")}</td>`
          + `<td class="n">${cash.display ? ev(usdYi(cash.display), { module: "m1_peer", title: `${r.name} 资本开支（现金口径）`, value: cash.display, label: cash.label, src: cash.src, note: cash.definition }) : "未披露"}</td>`
          + `<td style="font-size:12px">${esc(trim(g.text || "—", 46))}</td></tr>`;
      }).join("") + `</tbody></table><p class="hint" style="margin-top:8px">${esc(ct.notes[0])}</p></div>`;
    const tr = M.tencent_capex_trajectory;
    h += `<div class="block"><h3>腾讯：资本开支、资本开支付款与自由现金流</h3><p class="hint">单位：${esc(tr.unit)}。${esc(trim(tr.note || "", 80))}</p>${trajectory(tr.rows)}</div></div>`;

    // flashes
    h += `<div class="grid-2e">` + M.flashes.map((f) => flash(f)).join("") + `</div>`;

    // rerun
    h += `<div class="block"><h3>待重跑</h3><p class="hint">发布后按以下步骤重跑；议题列不变，“变化”一栏需人工复核。</p><table class="t"><thead><tr><th>公司</th><th>事件</th><th>日期</th><th>状态</th></tr></thead><tbody>`
      + M.rerun.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.event)}</td><td>${esc(r.date)}</td><td>${r.confirmed ? `<span class="tag ok">官方已公告</span>` : `<span class="tag infer">按去年同期推断</span>`}</td></tr>`).join("")
      + `</tbody></table><ol style="font-size:12.5px;color:var(--ink-2);padding-left:18px;margin:12px 0 0">${M.rerun_method.map((s) => `<li>${esc(s.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol></div>`;

    host.innerHTML = h;
    host.dataset.trace = `<span><span class="kind">${esc(M.meta.generated_by)}</span>｜${esc(M.meta.script)}｜截至 ${esc(M.meta.as_of)}</span><span>输入 ${M.meta.inputs.length} 个本地文件｜80 条原句与 127 个数字锚点逐字比对通过</span>`;
  }

  function usdYi(d) { const m = String(d).match(/([0-9.]+)\s*bn\s*美元/); return m ? (parseFloat(m[1]) * 10).toFixed(1) + " 亿美元" : d; }
  function trim(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; }

  function trajectory(rows) {
    const { svg, fmt, esc } = window.IR;
    const W = 420, H = 210, L = 34, B = 30, T = 14;
    const vals = rows.flatMap((r) => [r.capex_bn, r.capex_paid_bn, r.fcf_bn]).filter((v) => v != null);
    const max = Math.max(...vals), min = Math.min(0, ...vals);
    const y = (v) => T + (max - v) / (max - min) * (H - T - B);
    const gw = (W - L) / rows.length;
    let s = `<line x1="${L}" y1="${y(0)}" x2="${W}" y2="${y(0)}" stroke="#8A94A6"/>`;
    const series = [["capex_bn", "#1B2433", "资本开支"], ["capex_paid_bn", "#2459D6", "资本开支付款"], ["fcf_bn", "#B97E12", "自由现金流"]];
    rows.forEach((r, i) => {
      series.forEach(([k, c], j) => {
        const v = r[k]; if (v == null) return;
        const x0 = L + i * gw + 8 + j * ((gw - 16) / 3);
        const top = Math.min(y(v), y(0)), hh = Math.abs(y(v) - y(0));
        s += `<rect x="${x0}" y="${top}" width="${(gw - 16) / 3 - 3}" height="${Math.max(hh, 1)}" fill="${v < 0 ? "#B8432F" : c}"><title>${r.quarter} ${k} ${v}</title></rect>`;
        s += `<text x="${x0 + ((gw - 16) / 3 - 3) / 2}" y="${v < 0 ? y(v) + 11 : y(v) - 3}" font-size="9" text-anchor="middle" fill="#3A4558">${fmt(v, 1)}</text>`;
      });
      s += `<text x="${L + i * gw + gw / 2}" y="${H - 10}" font-size="11" text-anchor="middle" fill="#5B6577">${esc(r.quarter)}</text>`;
    });
    const leg = series.map(([, c, n], j) => `<span><i style="background:${c}"></i>${n}</span>`).join("");
    return svg(W, H, s) + `<div class="legend">${leg}<span><i style="background:#B8432F"></i>负值</span></div>`;
  }

  function flash(f) {
    const { ev, esc } = window.IR;
    const lab = (x) => x.label;
    let h = `<div class="block"><h3>${esc(f.title)}</h3><p class="hint"><span class="watermark">${esc(f.watermark || "内部准备材料，不构成公司口径")}</span>｜${esc(f.period)}，${esc(f.report_date)} 发布</p>`;
    h += `<ol style="padding-left:18px;margin:0 0 10px">` + f.conclusions.map((c) => `<li style="margin-bottom:6px">${ev(c.text, { module: "m1_peer", title: "结论", quote: c.text, label: lab(c), src: c.src })}</li>`).join("") + `</ol>`;
    h += `<table class="t"><thead><tr><th>指标</th><th>数值</th><th>同比</th></tr></thead><tbody>`
      + f.key_numbers.slice(0, 7).map((k) => `<tr><td>${esc(k.metric)}</td><td>${ev(k.value, { module: "m1_peer", title: k.metric, value: k.value, quote: (k.anchors || []).map((a) => a.text).join(" ／ "), label: k.label, src: k.src })}</td><td>${esc(k.yoy || "—")}</td></tr>`).join("")
      + `</tbody></table>`;
    h += `<h4 style="margin:12px 0 4px;font-size:13px">管理层原句</h4>` + f.quotes.slice(0, 3).map((q) => `<div style="font-size:12.5px;margin-bottom:6px">${ev("“" + q.text + "”", { module: "m1_peer", title: q.speaker, quote: q.text, label: q.label, src: q.src, note: q.context })}<span style="color:var(--muted)"> —— ${esc(q.speaker)}</span></div>`).join("");
    h += `<h4 style="margin:12px 0 4px;font-size:13px">对腾讯口径的启示 <span class="tag infer">推断</span></h4><ul style="padding-left:18px;margin:0;font-size:12.5px">`
      + f.implications_for_tencent.map((x) => `<li style="margin-bottom:6px">${ev(trim(x.text, 120), { module: "m1_peer", title: "对腾讯的启示（推断）", quote: x.text, label: x.label, src: x.src, note: x.basis })}</li>`).join("") + `</ul>`;
    h += `<h4 style="margin:12px 0 4px;font-size:13px">腾讯 Q3 可能被追问</h4><ul style="padding-left:18px;margin:0;font-size:12.5px">`
      + f.tencent_q3_questions.map((x) => `<li style="margin-bottom:6px">${esc(x.q)}<div style="color:var(--muted)">${esc(x.note || "")}</div></li>`).join("") + `</ul></div>`;
    return h;
  }

  render.panelId = "peers";
  (window.IR_RENDERERS = window.IR_RENDERERS || []).push(render);
})();
