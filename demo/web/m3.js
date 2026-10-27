/* Panel 4: 股东·资金·回购 — southbound, buyback calendar with the two-layer blackout, holders, read-only alerts */
(function () {
  "use strict";
  function render() {
    const { D, ev, esc, fmt } = window.IR;
    const host = document.getElementById("holders");
    const M = D.m3_holders;
    if (!M) { host.innerHTML = `<p class="sub">本模块数据尚未生成。</p>`; return; }
    const sb = M.southbound, bb = M.buyback, bl = M.blackout.layers;
    const E = (text, title, o) => ev(text, Object.assign({ module: "m3_holders", title }, o));

    let h = `<h2 class="lede">南向持股年内累计增加 0.97 个百分点；2026 年回购 324.44 亿港元已逐份对账，最后一笔在 10 月 15 日</h2>`;
    h += `<p class="sub">数据全部来自港交所披露易与公司定期报告；资金流为估算（持股变化 × 收盘价），因果解释一律不写。只读监测，不提供任何交易或回购建议。</p>`;
    h += `<div class="score" style="margin-bottom:22px">` + M.headline.map((x) => `<div><div class="v" style="font-size:20px">${E(shortVal(x), x.text, { value: x.text, label: x.label, src: x.src })}</div><div class="l">${esc(trim(x.text, 40))}</div></div>`).join("") + `</div>`;

    // southbound chart + changes
    h += `<div class="grid-2"><div class="block"><h3>港股通（南向）持股比例</h3><p class="hint">${esc(sb.series[0].date)} 至 ${esc(sb.latest.date)}，${sb.series.length} 个交易日；页面公布值保留两位小数。</p>${southChart(sb)}</div>`;
    h += `<div class="block"><h3>持股变化与估算资金流</h3><p class="hint">${esc(trim(sb.price_note, 70))}</p><table class="t"><thead><tr><th>区间</th><th class="n">持股变化</th><th class="n">估算净买入</th></tr></thead><tbody>`;
    const lab = { "since_2025_10_31": "2025-10-31 以来", "ytd_since_2025-12-31": "年初以来", "since_2026-09-30": "9 月末以来", "last_5_trading_days": "最近 5 个交易日", "last_20_trading_days": "最近 20 个交易日" };
    Object.entries(sb.changes).forEach(([k, c]) => {
      h += `<tr><td>${esc(lab[k] || k)}</td><td class="n">${fmt(c.d_pp, 2)} 个百分点</td><td class="n">${E(fmt(c.net_yi_est_sum, 1) + " 亿港元", "估算净买入（" + (lab[k] || k) + "）", { label: c.label, src: c.src, note: `${c.from} 至 ${c.to}，持股 ${fmt(c.d_shares, 0)} 股；${sb.definition}` })}</td></tr>`;
    });
    const ac = sb.alignment_check, best = ac.result[ac.best] || {};
    h += `</tbody></table><p class="hint" style="margin-top:10px">交叉核对：持股变化与港交所成交净额（滞后 ${esc(String(ac.best).replace("lag_", ""))} 个交易日）的相关系数 ${E(fmt(best.pearson, 4), "估算方法交叉核对", { label: ac.label, src: ac.src, note: ac.method + "；重叠 " + ac.overlap_days + " 天" })}，说明“持股变化 × T-2 收盘价”的估算口径可靠。</p></div></div>`;

    // buyback calendar + blackout
    h += `<div class="block"><h3>2026 年回购日历</h3><p class="hint">每格一个交易日，颜色越深回购金额越大；黄色斜纹为按上市规则计算的禁止窗口（计算），红框为最后一笔回购（公开披露）；黑框为业绩公告日。两层分开画，不推断停止原因。</p>${calendar(bb, bl)}`;
    h += `<div class="grid-2e" style="margin-top:14px"><div><span class="tag calc">计算</span> ${esc(bl.rule_window_calc.text.replace("【计算】", ""))}</div><div><span class="tag public">公开披露</span> ${esc(bl.observed_disclosure.text.replace("【公开披露】", ""))} ${esc(bl.observed_gap_before_window.text)}</div></div>`;
    h += `<p style="margin:12px 0 0">${E("✓ " + bb.badge.text, "回购逐份对账", { value: `${bb.badge.days} 个交易日、${fmt(bb.badge.shares, 0)} 股、${fmt(bb.badge.amount_yi, 2)} 亿港元`, label: bb.badge.label, src: bb.badge.src, note: bb.reconciliation.method })}</p></div>`;

    // anomalies + holders + ccass
    const an = bb.data_anomalies[0];
    h += `<div class="grid-2e">`;
    h += `<div class="block"><h3>大股东</h3><table class="t"><thead><tr><th>股东</th><th class="n">持股</th><th class="n">占比</th><th>日期</th></tr></thead><tbody>`
      + M.major_holders.table.map((r) => `<tr><td style="font-size:12px">${esc(trim(r.holder, 40))}</td><td class="n">${fmt(r.shares, 0)}</td><td class="n">${E(fmt(r.pct, 2) + "%", r.holder, { label: r.label, src: r.src })}</td><td>${esc(r.date)}</td></tr>`).join("")
      + `</tbody></table><p class="hint" style="margin-top:8px">Prosus 最近一次权益披露：${esc(M.major_holders.prosus_di_latest.event_date)}，${fmt(M.major_holders.prosus_di_latest.pct, 2)}%。董事个人交易不展示。</p>`;
    if (an) h += `<div style="margin-top:12px;padding:10px 12px;background:var(--amber-soft);font-size:12.5px"><b>需人工复核的报表字段</b>（工具只提示、不判断）：${E(trim(an.text, 120), "翌日披露报表数值不自洽", { quote: an.text, label: an.label, src: an.src, note: an.url })}</div>`;
    h += `</div>`;
    h += `<div class="block"><h3>中央结算系统（CCASS）托管商持股 Top10</h3><p class="hint">托管商层级，不是最终受益人；截至 ${esc(M.ccass.as_of)}。</p><table class="t"><thead><tr><th>参与者</th><th class="n">占比</th><th class="n">较 10-16</th><th class="n">较年初</th></tr></thead><tbody>`
      + M.ccass.top10.map((r) => `<tr><td style="font-size:12px">${esc(trim(r.name, 30))}</td><td class="n">${E(fmt(r.pct, 2) + "%", r.name, { value: fmt(r.shares, 0) + " 股", label: r.label, src: r.src })}</td><td class="n">${signed(r.d_shares_vs_2026_10_16)}</td><td class="n">${signed(r.d_shares_vs_2025_12_31)}</td></tr>`).join("")
      + `</tbody></table></div></div>`;

    // alerts
    h += `<div class="block"><h3>只读告警规则</h3><p class="hint">${esc(M.alerts.disclaimer)}</p><table class="t"><thead><tr><th>规则</th><th>条件</th><th>状态</th><th>最近命中</th></tr></thead><tbody>`
      + M.alerts.rules.map((r) => `<tr><td><b>${esc(r.id)}</b> ${esc(r.name)}</td><td style="font-size:12px">${esc(r.condition)}</td><td>${r.triggered ? `<span class="tag warn">已触发</span>` : `<span class="tag">未触发</span>`}</td><td style="font-size:12px">${esc((r.hits || []).slice(-2).map((x) => (x.trade_date || x.date) + (x.net_yi != null ? " " + x.net_yi + " 亿" : x.d_pp != null ? " " + x.d_pp + "pp" : "")).join("；"))}</td></tr>`).join("")
      + `</tbody></table></div>`;

    host.innerHTML = h;
    host.dataset.trace = `<span><span class="kind">${esc(M.meta.generated_by)}</span>｜${esc(M.meta.script)}｜截至 ${esc(M.meta.as_of)}</span><span>输入 ${M.meta.inputs.length} 个文件｜自检 ${esc(M.meta.self_check.summary.checks_passed)}/${esc(M.meta.self_check.summary.checks_total)}，抽查 ${esc(M.meta.self_check.summary.spot_passed)}/${esc(M.meta.self_check.summary.spot_total)}</span>`;
  }

  function trim(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; }
  function signed(v) { if (v == null) return "—"; const s = Math.round(v / 1e4); return (s > 0 ? "+" : "") + s.toLocaleString("zh-CN") + " 万股"; }
  function shortVal(x) {
    if (x.unit === "%") return window.IR.fmt(x.value, 2) + "%";
    if (x.unit === "pp") return "+" + window.IR.fmt(x.value, 2) + "pp";
    if (x.unit === "亿港元") return window.IR.fmt(x.value, 2) + " 亿";
    return String(x.value).slice(5) || String(x.value);
  }

  function southChart(sb) {
    const { svg, scale, dateNum, esc } = window.IR;
    const s0 = sb.series;
    const W = 640, H = 230, L = 40, R = 12, T = 12, B = 26;
    const xs = s0.map((p) => dateNum(p.date)), ys = s0.map((p) => p.pct);
    const x = scale(Math.min(...xs), Math.max(...xs), L, W - R);
    const lo = Math.floor(Math.min(...ys) * 4) / 4, hi = Math.ceil(Math.max(...ys) * 4) / 4;
    const y = scale(lo, hi, H - B, T);
    let s = "";
    for (let v = lo; v <= hi + 1e-9; v += 0.25) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#EBEEF3"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#8A94A6">${v.toFixed(2)}%</text>`;
    const months = [...new Set(s0.map((p) => p.date.slice(0, 7)))];
    months.forEach((m, i) => { if (i % 2 === 0) { const d = s0.find((p) => p.date.startsWith(m)); s += `<text x="${x(dateNum(d.date))}" y="${H - 8}" font-size="10" fill="#8A94A6">${m.slice(2).replace("-", "/")}</text>`; } });
    s += `<polyline fill="none" stroke="#2459D6" stroke-width="1.8" points="${s0.map((p) => x(dateNum(p.date)).toFixed(1) + "," + y(p.pct).toFixed(1)).join(" ")}"/>`;
    const last = s0[s0.length - 1];
    s += `<circle cx="${x(dateNum(last.date))}" cy="${y(last.pct)}" r="3.5" fill="#2459D6"/><text x="${x(dateNum(last.date)) - 6}" y="${y(last.pct) - 8}" font-size="11" text-anchor="end" fill="#2459D6" font-weight="700">${last.pct.toFixed(2)}%</text>`;
    return svg(W, H, s);
  }

  function calendar(bb, bl) {
    const { svg, dateNum, esc } = window.IR;
    const days = bb.calendar;
    const first = dateNum(days[0].date);
    const firstDow = (new Date(days[0].date + "T00:00:00Z").getUTCDay() + 6) % 7; // Mon=0
    const cell = 13, gap = 2, L = 26, T = 18;
    const max = Math.max(...days.map((d) => d.amount_yi || 0));
    const winStart = dateNum(bl.rule_window_calc.start), winEnd = dateNum(bl.rule_window_calc.end);
    const lastBB = dateNum(bl.observed_disclosure.last_buyback);
    let s = `<defs><pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" fill="#FBF1DC"/><line x1="0" y1="0" x2="0" y2="5" stroke="#E2B65C" stroke-width="2"/></pattern></defs>`;
    let maxCol = 0;
    const endDay = dateNum("2026-11-20");
    for (let d = first; d <= endDay; d++) {
      const dow = (new Date(d * 86400000).getUTCDay() + 6) % 7;
      if (dow > 4) continue;
      const col = Math.floor((d - first + firstDow) / 7);
      maxCol = Math.max(maxCol, col);
      const iso = new Date(d * 86400000).toISOString().slice(0, 10);
      const rec = days.find((x) => x.date === iso);
      const amt = rec ? rec.amount_yi || 0 : 0;
      const inWin = d >= winStart && d <= winEnd;
      let fill = "#F1F3F6";
      if (amt > 0) { const t = Math.min(1, amt / max); fill = `rgb(${Math.round(220 - 186 * t)},${Math.round(229 - 140 * t)},${Math.round(250 - 36 * t)})`; }
      else if (inWin) fill = "url(#hatch)";
      const X = L + col * (cell + gap), Y = T + dow * (cell + gap);
      s += `<rect x="${X}" y="${Y}" width="${cell}" height="${cell}" rx="2" fill="${fill}" ${d === lastBB ? 'stroke="#B8432F" stroke-width="2"' : ""}${rec && rec.results_day ? ' stroke="#1B2433" stroke-width="1.5"' : ""}><title>${iso}${amt ? " 回购 " + amt + " 亿港元" : ""}${inWin ? "（规则窗口，计算）" : ""}</title></rect>`;
      if (new Date(d * 86400000).getUTCDate() <= 7 && dow === 0) s += `<text x="${X}" y="${T - 6}" font-size="10" fill="#8A94A6">${iso.slice(5, 7)}月</text>`;
    }
    ["一", "三", "五"].forEach((w, i) => { s += `<text x="${L - 8}" y="${T + i * 2 * (cell + gap) + 10}" font-size="10" text-anchor="end" fill="#8A94A6">${w}</text>`; });
    const W = L + (maxCol + 1) * (cell + gap) + 4, H = T + 5 * (cell + gap) + 4;
    return `<div style="overflow-x:auto">${svg(W, H, s)}</div>`;
  }

  render.panelId = "holders";
  (window.IR_RENDERERS = window.IR_RENDERERS || []).push(render);
})();
