/* Panel 1: 今日简报 — countdown, earnings-season calendar strip, what to look at first */
(function () {
  "use strict";
  function render() {
    const { D, ev, esc, svg, fmt, dateNum } = window.IR;
    const host = document.getElementById("brief");
    const R = D.m2_radar, M1 = D.m1_peer, M3 = D.m3_holders, M4 = D.m4_gatekeeper;
    const asOf = (R && R.meta.as_of) || "2026-10-26";
    const board = "2026-11-18";
    const days = Math.round(dateNum(board) - dateNum(asOf));
    const win = M3 && M3.blackout.layers.rule_window_calc;
    const last = M3 && M3.blackout.layers.observed_disclosure;

    let h = `<div class="hero"><div>`;
    h += `<p class="countdown">距 Q3 业绩董事会还有 ${ev(days + " 天", { module: "m1_peer", title: "Q3 业绩董事会会议", value: board, label: "公开披露", src: ["S16"], note: "港交所 2026-09-24 董事会会议通知" })}`
      + `<small>${esc(asOf)} 视角｜11 月 18 日审议并公布 2026 年第三季度业绩</small></p>`;
    h += `<div class="calendar block flat" style="margin-top:18px">${calendar(asOf, board, win, last, M1)}</div>`;
    h += `<div class="legend"><span><i style="background:#F3E3BF"></i>回购规则窗口（计算）</span><span><i style="background:var(--red)"></i>最后一笔回购（公开披露）</span><span><i style="background:var(--ink)"></i>同业与公司事件</span><span><i style="background:var(--blue)"></i>今天</span></div>`;
    h += `</div><div class="block"><h3>暂无已公开表述的高频议题</h3><p class="hint">来自问题雷达：工具只标注暂无已公开表述的议题，不建议口径；如何处理由部门按流程决定。</p><ul class="brief-list">`;
    const p0 = R ? R.gaps_for_management.filter((g) => g.priority === "P0").slice(0, 3) : [];
    p0.forEach((g, i) => {
      h += `<li><span class="num">${i + 1}</span><b>${esc(g.title)}</b><div style="font-size:12.5px;color:var(--ink-2);margin-top:4px">`
        + ev(trim(g.items, 70), { module: "m2_radar", title: g.title, quote: g.items, label: g.label, src: g.src, note: g.note }) + `</div></li>`;
    });
    h += `</ul></div></div>`;

    // KPI strip
    const tencentCapex = M1 && M1.capex_table.rows.find((r) => r.company === "tencent");
    const meta = M1 && M1.capex_table.rows.find((r) => r.company === "meta");
    const hl = (k) => M3 && M3.headline.find((x) => x.key === k);
    const sb = hl("southbound_pct"), bb = hl("buyback_badge");
    const inj = M4 && M4.injection;
    h += `<div class="score" style="margin:26px 0">`;
    if (sb) h += cell(ev(fmt(sb.value, 2) + "%", { module: "m3_holders", title: "南向持股比例", value: sb.text, label: sb.label, src: sb.src }), `南向持股（${sb.as_of}）`);
    if (bb) h += cell(ev(fmt(bb.value, 2) + " 亿", { module: "m3_holders", title: "2026 年回购金额（港元）", value: bb.text, label: bb.label, src: bb.src }), "年内回购（港元，已逐份对账）");
    if (tencentCapex) h += cell(ev(tencentCapex.company_basis.display, { module: "m1_peer", title: "腾讯 2Q26 资本开支（公司口径）", value: tencentCapex.company_basis.display + "，同比 " + tencentCapex.company_basis.yoy_display, label: tencentCapex.company_basis.label, src: tencentCapex.company_basis.src, note: tencentCapex.company_basis.definition }), "腾讯 2Q26 资本开支");
    if (meta) h += cell(ev(usdYi(meta.company_basis.display), { module: "m1_peer", title: "Meta 3Q26 资本开支", value: meta.company_basis.display, label: meta.company_basis.label, src: meta.company_basis.src, note: meta.company_basis.definition }), "Meta 3Q26 资本开支（10-21 已发布）");
    if (R) h += cell(`${R.questions.length}｜${R.gaps_for_management.length}`, `雷达议题｜暂无已公开表述`);
    if (inj) h += cell(ev(fmt(inj.recall * 100, 1) + "%", { module: "m4_gatekeeper", title: "注入错误检出率（种子 7）", value: `${inj.detected}/${inj.n}`, label: "计算", src: inj.src }), "数字守门员检出率");
    h += `</div>`;

    // changes since 10-19 + top10
    h += `<div class="grid-2"><div class="block"><h3>10 月 19 日以来的变化</h3><p class="hint">只列公开事实；每条已映射到受影响的雷达议题。</p><ul class="brief-list">`;
    (R ? R.changes_since_1019 : []).filter((c) => !(c.flags || []).some((f) => /公司未证实/.test(f))).forEach((c) => {
      h += `<li><span class="num">${esc(c.date.slice(5))}</span><b>${esc(c.title)}</b>${(c.flags || []).length ? ` <span class="tag infer">${esc(c.flags.join("、"))}</span>` : ""}`
        + `<div style="font-size:12.5px;color:var(--ink-2);margin-top:4px">${ev(trim(c.detail, 90), { module: "m2_radar", title: c.title, quote: c.detail, label: c.label, src: c.src })}</div>`
        + `<div style="font-size:12px;color:var(--muted)">影响：${esc((c.impact || []).join("、"))}</div></li>`;
    });
    h += `</ul></div>`;
    if (R && R.top10_prereg) {
      const p = R.top10_prereg;
      h += `<div class="block"><h3>Q3 Top10 议题（会前预注册）</h3><p class="hint">按“全市场热度 0.60 + 近期事件 0.25 + 机构轨迹 0.15”排序；11-18 会后公开核对命中情况。</p><ol style="padding-left:20px;margin:0 0 12px">`
        + p.items.map((x) => `<li style="margin-bottom:6px">${esc(x.title)}</li>`).join("") + `</ol>`
        + `<div class="hint" style="margin:0">SHA-256 指纹（${esc(p.generated_at || "")}）</div><div class="mono-hash">${esc(p.sha256)}</div></div>`;
    }
    h += `</div>`;
    host.innerHTML = h;
    host.dataset.trace = `<span><span class="kind">本地 Python</span>｜汇总自同业矩阵、问题雷达、股东·资金·回购、数字守门员四个模块</span><span>截至 ${esc(asOf)}</span>`;
  }

  function usdYi(d) { const m = String(d).match(/([\d.]+)\s*bn\s*美元/); return m ? (parseFloat(m[1]) * 10).toFixed(1) + " 亿美元" : d; }
  function trim(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; }
  function cell(v, l) { return `<div><div class="v">${v}</div><div class="l">${l}</div></div>`; }

  function calendar(asOf, board, win, last, M1) {
    const { svg, dateNum, esc } = window.IR;
    const start = "2026-10-12", end = "2026-11-21";
    const W = 900, L = 10, Rm = 10, BAND = 86, BH = 34;
    const x = (d) => L + ((dateNum(d) - dateNum(start)) / (dateNum(end) - dateNum(start))) * (W - L - Rm);
    let s = `<rect x="${L}" y="${BAND}" width="${W - L - Rm}" height="${BH}" fill="#F5F6F8"/>`;
    if (win) s += `<rect x="${x(win.start)}" y="${BAND}" width="${x(win.end) - x(win.start)}" height="${BH}" fill="#F3E3BF"/><text x="${x(win.start) + 6}" y="${BAND + 21}" font-size="12" fill="#8A5D0C">回购规则窗口 ${esc(win.start.slice(5))}–${esc(win.end.slice(5))}（计算）</text>`;
    for (let d = dateNum(start); d <= dateNum(end); d++) {
      const dt = new Date(d * 86400000);
      const iso = dt.toISOString().slice(0, 10);
      const dow = dt.getUTCDay();
      s += `<line x1="${x(iso)}" y1="${BAND + BH}" x2="${x(iso)}" y2="${BAND + BH + (dow === 1 ? 8 : 4)}" stroke="#C9D0DB"/>`;
      if (dow === 1) s += `<text x="${x(iso)}" y="${BAND + BH + 22}" font-size="11" fill="#5B6577" text-anchor="middle">${iso.slice(5)}</text>`;
    }
    const events = [];
    if (last) events.push({ d: last.last_buyback, t: "最后一笔回购", c: "#B8432F", row: 0 });
    events.push({ d: "2026-10-21", t: "Meta Q3 发布", c: "#1B2433", row: 1 });
    (M1 ? M1.rerun : []).forEach((r) => {
      if (r.company === "tencent" || !/^\d{4}-\d{2}-\d{2}$/.test(r.date)) return;
      events.push({ d: r.date, t: `${r.name} 业绩`, c: "#1B2433", row: 0 });
    });
    events.push({ d: "2026-10-29", t: "腾讯全球数字生态大会", c: "#1B2433", row: 1 });
    events.push({ d: board, t: "Q3 业绩董事会", c: "#1B2433", row: 0, bold: true });
    events.sort((a, b) => dateNum(a.d) - dateNum(b.d));
    const placed = { 0: [], 1: [] };
    events.forEach((e) => {
      const xx = x(e.d);
      const lvl = placed[e.row].filter((p) => Math.abs(p - xx) < 150).length;
      placed[e.row].push(xx);
      const right = xx > W - 160;
      const y = e.row === 0 ? 18 + lvl * 15 : BAND + BH + 44 + lvl * 15;
      const tx = right ? xx - 5 : xx + 5;
      s += `<line x1="${xx}" y1="${e.row === 0 ? y + 4 : BAND + BH}" x2="${xx}" y2="${e.row === 0 ? BAND : y - 11}" stroke="${e.c}" stroke-width="1" opacity="0.7"/>`;
      s += `<circle cx="${xx}" cy="${e.row === 0 ? BAND : BAND + BH}" r="3.5" fill="${e.c}"/>`;
      s += `<text x="${tx}" y="${y}" font-size="11.5" fill="${e.c}" text-anchor="${right ? "end" : "start"}" ${e.bold ? 'font-weight="700"' : ""}>${esc(e.d.slice(5))} ${esc(e.t)}</text>`;
    });
    s += `<line x1="${x(asOf)}" y1="${BAND - 14}" x2="${x(asOf)}" y2="${BAND + BH + 10}" stroke="#2459D6" stroke-width="2"/><text x="${x(asOf)}" y="${BAND - 18}" font-size="12" font-weight="700" fill="#2459D6" text-anchor="middle">今天</text>`;
    return svg(W, BAND + BH + 80, s);
  }

  render.panelId = "brief";
  (window.IR_RENDERERS = window.IR_RENDERERS || []).push(render);
})();
