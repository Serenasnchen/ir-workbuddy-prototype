/* Panel 5: 数字守门员 — live draft checker, injection scoreboard, five-document tie-out, three capex bases */
(function () {
  "use strict";
  function render() {
    const { D, ev, esc, fmt } = window.IR;
    const host = document.getElementById("gatekeeper");
    const M = D.m4_gatekeeper;
    if (!M) { host.innerHTML = `<p class="sub">本模块数据尚未生成。</p>`; return; }
    const inj = M.injection, rob = inj.robustness, fp = inj.false_positive_test, tie = M.tieout;
    const E = (text, title, o) => ev(text, Object.assign({ module: "m4_gatekeeper", title }, o));

    let h = `<h2 class="lede">数字一律交给脚本：330 个单元格约 3 秒比对完，样本外注入 600 处错误检出 98.5%</h2>`;
    h += `<p class="sub">确定性代码（正则 + 单位归一 + 四舍五入区间比较），不靠大模型判断数字对错。演示只用已发布的 2026Q2 材料；处理未公布业绩时必须在私有化环境运行。</p>`;

    // live checker
    const demo = M.js_registry.demo;
    h += `<div class="grid-2"><div class="block checker"><h3>现场试一下：改一个数字</h3><p class="hint">在下面的草稿里改任意数字（例如把 528 改成 582），对应指标会立刻变红。规则与后台脚本一致的简化版，只检查点名了指标的句子。</p>`
      + `<textarea id="gk-input" spellcheck="false">${esc(demo.input_zh.replace("582", "528"))}\n二零二六年第二季的收入为人民币2,048亿元，同比增长11%。\nCapital expenditure was RMB52.8 billion, up 176% YoY.</textarea>`
      + `<div class="out" id="gk-out"></div><div class="legend"><span><i style="background:var(--green-soft);border:1px solid var(--green)"></i>与已披露一致</span><span><i style="background:var(--red-soft);border:1px solid var(--red)"></i>与已披露冲突</span></div></div>`;

    // scoreboard
    h += `<div class="block"><h3>注入错误记分牌</h3><p class="hint">在已发布的中英文新闻稿上按固定随机种子注入错误，模拟“草稿”。</p><div class="score" style="grid-template-columns:1fr 1fr">`
      + cell(E(fmt(inj.recall * 100, 1) + "%", "召回率（种子 7）", { value: `${inj.detected}/${inj.n}`, label: inj.label, src: inj.src }), `召回率｜种子 ${inj.seed}，${inj.n} 处`)
      + cell(E(fmt(rob.recall * 100, 1) + "%", "样本外召回率", { value: `${rob.detected}/${rob.n}`, label: rob.label, src: rob.src, note: rob.note }), `样本外｜种子 ${rob.seeds}，${rob.n} 处`)
      + cell(E(fmt(fp.fp_rate_red * 100, 1) + "%", "红色误报率", { value: `${fp.flagged_red}/${fp.paragraphs}`, label: fp.label, src: fp.src, note: fp.design }), `红色误报｜${fp.paragraphs} 段干净文本`)
      + cell(E(fmt(fp.fp_rate_any * 100, 1) + "%", "含黄色提示的比例", { value: `${fp.flagged_any}/${fp.paragraphs}`, label: fp.label, src: fp.src }), `含黄色“新数字”提示`)
      + `</div><table class="t" style="margin-top:12px"><thead><tr><th>错误类型</th><th class="n">种子 7</th><th class="n">样本外</th></tr></thead><tbody>`
      + inj.categories.map((c, i) => { const r2 = rob.by_category[i] || {}; return `<tr><td>${esc(c.name)}</td><td class="n">${c.detected}/${c.n}</td><td class="n">${r2.detected != null ? r2.detected + "/" + r2.n : "—"}</td></tr>`; }).join("")
      + `</tbody></table>`;
    const miss = inj.misses[0];
    if (miss) h += `<p style="font-size:12.5px;margin:10px 0 0"><span class="tag warn">失败样例</span> ${esc(miss.desc)}（${esc(miss.cat_zh)}）：英文原文精度较粗（“2 million”），中文一侧在精度范围内的改动无法识别。</p>`;
    h += `</div></div>`;

    // tie-out
    h += `<div class="block"><h3>五方勾稽回放：2Q26 英文新闻稿、中文新闻稿、港交所英文与中文公告、业绩演示</h3><p class="hint">${tie.n_metrics} 个指标 × 5 份文件：一致 ${tie.summary["一致"]}，不一致 ${tie.summary["不一致"]}，未出现 ${tie.summary["未出现"]}。另有 ${tie.rounding_cases.length} 处仅为四舍五入显示差异，判定为一致。</p>`;
    h += `<table class="t"><thead><tr><th>指标</th><th>发现</th><th>对照</th><th>判断</th></tr></thead><tbody>`
      + dedupe(tie.discrepancies).map((d) => `<tr><td><b>${esc(d.name_zh)}</b><div style="color:var(--muted);font-size:12px">${esc(DOCN[d.doc] || d.doc)}${d.times > 1 ? "，出现 " + d.times + " 次" : ""}</div></td>`
        + `<td>${E(d.found, d.name_zh + "：正文", { quote: d.found_at && d.found_at.quote, label: d.label, src: d.src, note: d.found_at ? `${d.found_at.file}（第 ${d.found_at.line} 行）` : "" })}</td>`
        + `<td>${E(d.expected, d.name_zh + "：表格", { quote: d.expected_at && d.expected_at.quote, label: "公开披露", src: d.src, note: d.expected_at ? `${d.expected_at.file}（第 ${d.expected_at.line} 行）` : "" })}</td>`
        + `<td><span class="tag infer">${esc(d.judgement)}</span><div style="font-size:12px;color:var(--ink-2);margin-top:4px">${esc(trim(d.note || "", 90))}</div></td></tr>`).join("")
      + `</tbody></table><p class="hint" style="margin-top:10px">同一规则用于 2025Q1–2026Q1：共 ${tie.other_quarters_discrepancies.items.length} 处正文与表格的末位差异，多数符合截断取值（推断，需财务确认）。工具只把差异摆出来，是否属于取值惯例由财务确认。</p></div>`;

    // capex three bases
    const cx = M.capex;
    h += `<div class="block"><h3>资本开支的三套口径</h3><p class="hint">${esc(cx.reading)}</p><table class="t"><thead><tr><th>口径</th><th>期间</th><th class="n">金额</th></tr></thead><tbody>`
      + cx.rows.map((r) => `<tr><td style="font-size:12.5px">${esc(r.basis)}</td><td>${esc(r.period)}</td><td class="n">${E(r.display, r.basis + " " + r.period, { label: r.label, src: r.src, note: r.at ? (r.at.file || "") + (r.at.line ? "（第 " + r.at.line + " 行）" : "") : "" })}</td></tr>`).join("")
      + `</tbody></table></div>`;

    host.innerHTML = h;
    host.dataset.trace = `<span><span class="kind">${esc(M.meta.generated_by)}</span>｜${esc((M.meta.scripts || [M.meta.script]).join("、"))}｜截至 ${esc(M.meta.as_of)}</span><span>输入 ${M.meta.inputs.length} 个官方文件｜抽查 ${esc(M.meta.self_check.spot_checks_pass)}</span>`;
    wireChecker(M.js_registry);
  }

  function trim(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; }
  const DOCN = { release_en: "英文新闻稿", release_zh: "中文新闻稿", hkex_en: "港交所英文公告", hkex_zh: "港交所中文公告", ppt: "业绩演示" };
  function dedupe(list) {
    const seen = {};
    const out = [];
    list.forEach((d) => { const k = d.metric + "|" + d.doc; if (seen[k]) { seen[k].times += 1; return; } seen[k] = Object.assign({ times: 1 }, d); out.push(seen[k]); });
    return out;
  }
  function cell(v, l) { return `<div><div class="v">${v}</div><div class="l">${l}</div></div>`; }

  function wireChecker(reg) {
    const { esc } = window.IR;
    const input = document.getElementById("gk-input"), out = document.getElementById("gk-out");
    if (!input || !window.M4Check) { if (out) out.textContent = "检查器未加载"; return; }
    const run = () => {
      const text = input.value;
      let marks = [], off = 0;
      text.split("\n").forEach((line) => {
        const lang = /[一-鿿]/.test(line) ? "zh" : "en";
        try { (window.M4Check.check(line, reg, lang) || []).forEach((m) => marks.push(Object.assign({}, m, { start: m.start + off, end: m.end + off }))); } catch (e) { console.error(e); }
        off += line.length + 1;
      });
      marks.sort((a, b) => a.start - b.start);
      let html = "", pos = 0;
      marks.forEach((m) => {
        if (m.start < pos) return;
        html += esc(text.slice(pos, m.start));
        html += `<span class="${m.status === "bad" ? "hit-bad" : "hit-ok"}" title="${esc(m.name + "：" + m.msg + (m.expected ? "（应为 " + m.expected + "）" : ""))}">${esc(text.slice(m.start, m.end))}</span>`;
        pos = m.end;
      });
      html += esc(text.slice(pos));
      const bad = marks.filter((m) => m.status === "bad");
      out.innerHTML = html.replace(/\n/g, "<br>") + `<div style="margin-top:8px;font-size:12.5px;color:${bad.length ? "var(--red)" : "var(--green)"}">${bad.length ? bad.map((m) => `${esc(m.name)}：${esc(m.msg)}`).join("；") : `检查了 ${marks.length} 处数字，全部与已披露一致`}</div>`;
    };
    input.addEventListener("input", run);
    run();
  }

  render.panelId = "gatekeeper";
  (window.IR_RENDERERS = window.IR_RENDERERS || []).push(render);
})();
