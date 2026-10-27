/* Panel 3: 问题雷达 — transcript insights (12 quarters) + Q3 question radar */
(function () {
  "use strict";
  function render() {
    const { D, ev, esc, svg, fmt, labelTag } = window.IR;
    const host = document.getElementById("radar");
    const T = D.m2_transcripts;
    const R = D.m2_radar;
    if (!T && !R) { host.innerHTML = `<p class="sub">本模块数据尚未生成。</p>`; return; }
    const TAX = {};
    ((T && T.taxonomy) || []).forEach((t) => { TAX[t.id] = t.name.replace(/\(.*\)|（.*）/, ""); });
    const tname = (id) => TAX[id] || id;
    let html = "";

    // ---------- lede ----------
    const gap = T && T.gap;
    const rows = gap ? [...gap.rows].sort((a, b) => b.gap_pp - a.gap_pp) : [];
    const roi = rows.find((r) => r.topic === "AI_ROI");
    const capex = rows.find((r) => r.topic === "AI_CAPEX");
    html += `<h2 class="lede">投资回报与资本开支：分析师关注度明显高于管理层主动提及，是 Q3 准备重点</h2>`;
    if (roi && capex) {
      html += `<p class="sub">最近四个季度（${esc(gap.window[0])}–${esc(gap.window[3])}），管理层发言中“投资回报”占话题命中的 `
        + ev(fmt(roi.push_share * 100, 1) + "%", { module: "m2_transcripts", title: "管理层主动提及占比：投资回报", value: fmt(roi.push_share * 100, 1) + "%", label: "计算", src: gap.src, note: gap.definition })
        + `，分析师问题中则有 ` + ev(fmt(roi.pull_share_units * 100, 0) + "%", { module: "m2_transcripts", title: "分析师关切：投资回报（问题单元占比）", value: fmt(roi.pull_share_units * 100, 0) + "%", label: "计算", src: gap.src, note: `样本：${gap.n_units} 个问题单元。${gap.definition}` })
        + ` 涉及它；资本开支同样是 ` + ev(fmt(capex.push_share * 100, 1) + "%", { module: "m2_transcripts", title: "管理层主动提及占比：资本开支", label: "计算", src: gap.src, note: gap.definition })
        + ` 对 ` + ev(fmt(capex.pull_share_units * 100, 0) + "%", { module: "m2_transcripts", title: "分析师关切：资本开支", label: "计算", src: gap.src, note: gap.definition })
        + `。这正是 Q3 业绩会最需要提前准备的地方。</p>`;
    }

    // ---------- gap dumbbell + keyword trends ----------
    html += `<div class="grid-2"><div class="block"><h3>管理层主动提及 × 分析师关注</h3><p class="hint">黑点：管理层话题占比；橙点：分析师问题占比（归一）。红线表示分析师关注高于管理层主动提及。样本 ${gap ? gap.n_units : "—"} 个问题单元、管理层 ${gap ? fmt(gap.mgmt_words, 0) : "—"} 词。</p>${gap ? dumbbell(rows) : ""}
      <div class="legend"><span><i style="background:var(--ink)"></i>管理层主动提及</span><span><i style="background:var(--amber)"></i>分析师关注</span><span><i style="background:var(--red)"></i>关注 > 提及</span></div></div>`;
    html += `<div class="block"><h3>关键词：管理层 vs 分析师（12 个季度）</h3><p class="hint">每根柱为当季提及次数，深色为管理层、橙色为分析师。2026Q2 WorkBuddy 管理层 27 次、分析师 4 次。</p>${T ? trends(T) : ""}</div></div>`;

    // ---------- radar questions ----------
    if (R) html += radarBlock(R, tname);

    // ---------- capex narrative + fidelity ----------
    html += `<div class="grid-2e">`;
    if (T) {
      const quotes = (T.narrative.quotes || []).filter((q) => /capex|资本/.test(q.group));
      html += `<div class="block"><h3>资本开支表态的演变</h3><p class="hint">管理层原话（第三方文字稿，非官方逐字稿，引用前以官方录音复核）。</p><ul class="brief-list">`
        + quotes.map((q) => `<li><span class="num">${esc(q.quarter)}</span>`
          + ev("“" + q.quote + "”", { module: "m2_transcripts", title: `${q.quarter} 管理层表态`, quote: q.quote, label: "公开披露", src: q.src || [], note: `${q.speaker_as_transcribed || ""}｜${q.quote_note || ""}` })
          + `<div style="color:var(--muted);font-size:12px">${esc(q.speaker_as_transcribed || "")}</div></li>`).join("") + `</ul></div>`;
      const fr = T.transcript_fidelity.rows;
      const bad = fr.filter((r) => r.status === "不一致");
      html += `<div class="block"><h3>第三方文字稿能直接引用吗？抽查 ${fr.length} 个数字</h3><p class="hint">把实录里管理层说的数字与官方演示材料逐一比对：${fr.length - bad.length} 项一致，${bad.length} 项是明显的转写错误——所以数字一律回到公告取。</p>`
        + `<table class="t"><thead><tr><th>季度</th><th>指标</th><th class="n">实录</th><th class="n">官方</th><th>结果</th></tr></thead><tbody>`
        + fr.map((r) => `<tr><td>${esc(r.quarter)}</td><td>${esc(r.item)}</td><td class="n">${ev(fmt(r.transcript_value), { module: "m2_transcripts", title: "实录原文", quote: r.transcript_phrase, label: "公开披露", src: [r.src[0]] })}</td><td class="n">${ev(fmt(r.official_value), { module: "m2_transcripts", title: "官方数字", value: fmt(r.official_value) + "（十亿元）", label: "公开披露", src: [r.src[1]], note: r.official_doc })}</td><td><span class="tag ${r.status === "不一致" ? "warn" : "ok"}">${esc(r.status)}</span></td></tr>`).join("")
        + `</tbody></table></div>`;
    }
    html += `</div>`;

    // ---------- institution trajectories + backtest ----------
    if (T) html += trajectoryBlock(T, tname);

    host.innerHTML = html;
    host.dataset.trace = traceLine([T, R]);
    wireRadarFilters();
  }

  function traceLine(mods) {
    const { esc } = window.IR;
    return mods.filter(Boolean).map((m) => `<span><span class="kind">${esc(m.meta.generated_by || "")}</span>｜${esc(m.meta.script || "")}｜截至 ${esc(m.meta.as_of || "")}</span>`).join("")
      + `<span>输入：12 个季度实录（StockAnalysis，第三方文字稿）+ 腾讯官网业绩材料</span>`;
  }

  const SHORT = { AI_CAPEX: "资本开支", AI_ROI: "投资回报", AI_PRODUCTS: "自有 AI 产品", MODELS: "混元模型", COMPUTE: "算力供给",
    CLOUD: "腾讯云与 Token", MARGIN: "利润率与折旧", CAPITAL: "回购与现金流", ADS: "营销服务", GAMES_DOM: "本土游戏",
    GAMES_INTL: "国际游戏", FINTECH: "金融科技", SOCIAL: "社交与内容", REG: "监管与地缘", PORTFOLIO: "投资组合" };

  function dumbbell(rows) {
    const { svg, fmt, esc } = window.IR;
    const W = 560, rowH = 24, top = 8, left = 100, right = 48;
    const H = top + rows.length * rowH + 22;
    const max = Math.max(...rows.map((r) => Math.max(r.push_share, r.pull_share_norm))) * 1.1;
    const x = (v) => left + (v / max) * (W - left - right);
    let s = "";
    [0, 0.05, 0.1, 0.15].filter((t) => t < max).forEach((t) => {
      s += `<line x1="${x(t)}" y1="${top}" x2="${x(t)}" y2="${H - 18}" stroke="#EBEEF3"/><text x="${x(t)}" y="${H - 4}" font-size="10" fill="#8A94A6" text-anchor="middle">${Math.round(t * 100)}%</text>`;
    });
    rows.forEach((r, i) => {
      const y = top + i * rowH + rowH / 2;
      const up = r.pull_share_norm > r.push_share;
      s += `<text x="${left - 8}" y="${y + 4}" font-size="11.5" text-anchor="end" fill="#1B2433">${esc(SHORT[r.topic] || r.topic)}</text>`;
      s += `<line x1="${x(r.push_share)}" y1="${y}" x2="${x(r.pull_share_norm)}" y2="${y}" stroke="${up ? "#B8432F" : "#C9D0DB"}" stroke-width="${Math.abs(r.gap_pp) > 4 ? 3 : 2}"/>`;
      s += `<circle cx="${x(r.push_share)}" cy="${y}" r="4.5" fill="#1B2433"/><circle cx="${x(r.pull_share_norm)}" cy="${y}" r="4.5" fill="#B97E12"/>`;
      if (Math.abs(r.gap_pp) >= 4) s += `<text x="${Math.max(x(r.push_share), x(r.pull_share_norm)) + 8}" y="${y + 4}" font-size="10.5" fill="${up ? "#B8432F" : "#5B6577"}">${r.gap_pp > 0 ? "+" : ""}${fmt(r.gap_pp, 1)}pp</text>`;
    });
    return svg(W, H, s);
  }

  function trends(T) {
    const { svg, esc } = window.IR;
    const pick = ["WorkBuddy", "Hunyuan/混元", "Yuanbao/元宝", "Xiaowei/小微", "capex", "ROI/ROIC/payback"];
    const qs = T.heat.quarters;
    return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 18px">` + pick.map((k) => {
      const row = T.keywords.rows.find((r) => r.keyword === k);
      if (!row) return "";
      const vals = qs.map((q) => row.by_quarter[q] || { mgmt: 0, analyst: 0 });
      const max = Math.max(4, ...vals.map((v) => v.mgmt + v.analyst));
      const W = 250, H = 78, bw = W / qs.length;
      let s = "";
      vals.forEach((v, i) => {
        const hm = (v.mgmt / max) * 56, ha = (v.analyst / max) * 56;
        s += `<rect x="${i * bw + 2}" y="${62 - hm - ha}" width="${bw - 4}" height="${hm}" fill="#1B2433"><title>${qs[i]} 管理层 ${v.mgmt}</title></rect>`;
        s += `<rect x="${i * bw + 2}" y="${62 - ha}" width="${bw - 4}" height="${ha}" fill="#B97E12"><title>${qs[i]} 分析师 ${v.analyst}</title></rect>`;
      });
      s += `<line x1="0" y1="62.5" x2="${W}" y2="62.5" stroke="#C9D0DB"/><text x="0" y="75" font-size="9.5" fill="#8A94A6">${qs[0]}</text><text x="${W}" y="75" font-size="9.5" fill="#8A94A6" text-anchor="end">${qs[qs.length - 1]}</text>`;
      const last = vals[vals.length - 1];
      return `<div><div style="font-size:12.5px;font-weight:600">${esc(k)} <span style="color:var(--muted);font-weight:400">最新季 ${last.mgmt} / ${last.analyst}</span></div>${svg(W, H, s)}</div>`;
    }).join("") + `</div>`;
  }

  function radarBlock(R, tname) {
    const { ev, esc, fmt } = window.IR;
    const qs = (R.questions || []).filter((q) => !/公司未证实/.test(JSON.stringify(q.flags || [])) && !/公司未证实/.test(q.sub_theme || ""));
    const themes = R.themes || [];
    const pubIdx = (q) => { const x = q.public_statement_index || q.official_position || {}; return x.statements || x; };
    let h = `<div class="block"><h3>Q3 业绩会问题雷达：${qs.length} 个议题</h3>`
      + `<p class="hint"><span class="watermark">${esc(R.watermark || "内部准备材料，不构成公司口径")}</span>｜只列已公开的管理层原话与出处；暂无公开表述的只做标注，不建议口径。</p>`;
    h += `<div class="filters" id="radar-filters"><button class="chip" aria-pressed="true" data-theme="">全部</button>`
      + themes.map((t) => `<button class="chip" aria-pressed="false" data-theme="${esc(t.name)}">${esc(t.name)}${t.heat ? "｜热度 " + t.heat : ""}</button>`).join("") + `</div>`;
    h += qs.map((q, i) => {
      const p = pubIdx(q);
      const pList = Array.isArray(p) ? p : [p];
      const pubHtml = pList.filter((x) => x && (x.quote || x.summary)).slice(0, 3).map((x) =>
        ev(x.quote ? "“" + x.quote + "”" : x.summary, { module: "m2_radar", title: "已公开表述" + (x.speaker ? "：" + x.speaker : ""), quote: x.quote || x.summary, label: x.label || "公开披露", src: x.src || [], status: (x.verify && x.verify.status) || x.status, note: [x.speaker, x.date, x.tier ? "层级 " + x.tier : "", x.note].filter(Boolean).join("｜") })
        + `<div style="color:var(--muted)">${esc(x.speaker || x.source || "")}${x.date ? "，" + esc(x.date) : ""}</div>`).join("<hr class='rule' style='margin:6px 0'>") || `<span class="tag warn">无公开表述</span>`;
      const evid = (q.evidence || []).slice(0, 2).map((e) => ev(e.point || e.source, { module: "m2_radar", title: e.source || "市场证据", quote: e.point, label: e.label || (/(券商|研报|大摩|高盛|瑞银|花旗|中金)/.test(e.source || "") ? "推断" : "公开披露"), src: e.src || [], note: [e.source, e.date, e.url].filter(Boolean).join("｜") })).join("<br>");
      return `<details class="q" data-theme="${esc(q.theme || "")}"><summary><span class="qn">${String(q.rank || q.priority || i + 1).padStart(2, "0")}</span>`
        + `<span class="qt">${esc(q.sub_theme || trimTxt(q.question_cn, 40))}</span>`
        + `<span class="meta"><span class="tag">${esc(q.theme || "")}</span><span class="tag ${q.sensitivity >= 4 ? "warn" : ""}">敏感 ${q.sensitivity ?? "—"}</span><span class="tag">热度 ${q.frequency ?? "—"}</span></span></summary>`
        + `<p style="margin:10px 0 0 44px;font-size:13.5px">${esc(q.question_cn || q.question || "")}</p><div class="quad"><div><h5>为什么现在会被问</h5>${esc(trimTxt((q.why_now && q.why_now.text) || q.why_now || "", 260))}</div><div><h5>市场证据</h5>${evid || "—"}</div><div><h5>已公开表述索引</h5>${pubHtml}</div><div><h5>暂无已公开表述之处</h5>${esc(trimTxt((q.needs_management_confirmation && q.needs_management_confirmation.text) || q.gap || "—", 260))}</div></div>`
        + `<div style="margin-left:44px;font-size:12px;color:var(--muted)">话题：${(q.topics || []).map(tname).join("、") || "—"}${q.question_en ? "｜EN: " + esc(q.question_en) : ""}</div></details>`;
    }).join("");
    h += `</div>`;
    const gaps = R.gaps_for_management || [];
    const drift = R.drift_examples || [];
    h += `<div class="grid-2e"><div class="block"><h3>暂无已公开表述的议题（${gaps.length} 项）</h3><p class="hint">工具只标注、不建议口径；是否回应、如何回应由部门按既定流程处理。</p><ol style="padding-left:18px;margin:0">`
      + gaps.map((g) => `<li style="margin-bottom:10px"><span class="tag ${g.priority === "P0" ? "warn" : g.priority === "P1" ? "infer" : ""}">${esc(g.priority || "")}</span> <b>${esc(g.title || "")}</b><div style="font-size:12.5px;color:var(--ink-2)">${ev(trimTxt(g.items || g.text || "", 110), { module: "m2_radar", title: g.title, quote: g.items, label: g.label, src: g.src || [], note: g.note })}</div></li>`).join("") + `</ol></div>`;
    h += `<div class="block"><h3>口径漂移（${drift.length} 例）</h3><p class="hint">同一议题，不同场合、不同语言的说法不一致，业绩会前需要统一。</p>`
      + drift.map((d) => {
        const sides = d.sides || [d.side_a || d.a || {}, d.side_b || d.b || {}]; const a = sides[0] || {}; const b = sides[1] || {};
        return `<div style="border-top:1px solid var(--rule);padding:10px 0"><div style="font-weight:600;margin-bottom:6px">${esc(d.title || d.topic || "")} <span class="tag">${esc(d.type || "")}</span></div>`
          + `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12.5px">`
          + [a, b].map((x) => `<div style="background:var(--paper);padding:8px">${ev("“" + (x.quote || x.text || "") + "”", { module: "m2_radar", title: x.source || "原文", quote: x.quote || x.text, label: "公开披露", src: x.src || [], note: [x.source, x.date, x.tier ? "层级 " + x.tier : ""].filter(Boolean).join("｜") })}<div style="color:var(--muted);margin-top:4px">${esc(x.side || x.source || "")}${x.speaker ? "｜" + esc(x.speaker) : ""}${x.date ? "，" + esc(x.date) : ""}</div></div>`).join("")
          + `</div>${d.observation ? `<div style="font-size:12px;color:var(--muted);margin-top:6px">${esc(d.observation)}</div>` : ""}</div>`;
      }).join("") + `</div></div>`;
    return h;
  }

  function trajectoryBlock(T, tname) {
    const { esc, fmt, ev } = window.IR;
    const orgs = T.org_trajectory.orgs.filter((o) => o.n_quarters >= 3).slice(0, 12);
    const qs = T.heat.quarters.slice(-4);
    const bt = T.backtest;
    let h = `<div class="block"><h3>机构历史关注话题（最近 4 个季度）</h3><p class="hint">以机构为单位记录公开提问轨迹，姓名只作附注（第三方文字稿，待录音复核）。不对个人做评价或打分。</p>`
      + `<table class="t"><thead><tr><th>机构</th>${qs.map((q) => `<th>${esc(q)}</th>`).join("")}</tr></thead><tbody>`
      + orgs.map((o) => `<tr><td><b>${esc(o.org)}</b></td>${qs.map((q) => { const c = o.quarters[q]; return `<td>${c ? c.topics.map((t) => `<span class="tag">${esc(tname(t))}</span>`).join("") : `<span style="color:var(--faint)">未提问</span>`}</td>`; }).join("")}</tr>`).join("")
      + `</tbody></table>`;
    h += `<p style="margin:14px 0 0;font-size:13px"><b>回测（只作合理性检查）</b>：用机构历史话题预测 2026Q2，命中率 `
      + ev(fmt(bt.precision_at2 * 100, 0) + "%", { module: "m2_transcripts", title: "机构轨迹法命中率", label: "计算", note: `${bt.method}；${bt.n_orgs} 家机构、${bt.n_predictions} 个预测` })
      + `，低于“全市场最热两个话题”的朴素基线 ` + ev(fmt(bt.baseline.precision_at2 * 100, 0) + "%", { module: "m2_transcripts", title: "朴素基线命中率", label: "计算", note: bt.baseline.rule })
      + `。因此 Q3 预注册以全市场热点为主、机构轨迹为辅；样本很小，不宜外推。</p></div>`;
    return h;
  }

  function trimTxt(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; }

  function wireRadarFilters() {
    const box = document.getElementById("radar-filters");
    if (!box) return;
    box.addEventListener("click", (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      box.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", c === b ? "true" : "false"));
      const th = b.dataset.theme;
      document.querySelectorAll("#radar details.q").forEach((d) => { d.style.display = !th || d.dataset.theme === th ? "" : "none"; });
    });
  }

  render.panelId = "radar";
  (window.IR_RENDERERS = window.IR_RENDERERS || []).push(render);
})();
