/* M4 数字守门员 —— 网页实时检查器（参考实现，无外部依赖）。
 * 用法：const marks = M4Check.check(text, DATA.m4_gatekeeper.js_registry, "zh"|"en"|undefined);
 * 返回 [{start, end, status: "ok"|"bad", metric, name, found, expected, kind: "value"|"yoy"|"qoq", msg}]
 * 规则与 demo/pipeline/gk_core.py 一致的简化版：别名命中 → 取其后（至下一别名/句末）第一个同类数值 →
 * 单位归一（百万/%/元）→ 四舍五入半单位区间比较；同比/环比同理。不调用任何模型或网络。
 */
(function (root) {
  "use strict";
  const PUNCT = { "（": "(", "）": ")", "，": ",", "；": ";", "：": ":", "％": "%", "－": "-", "–": "-", "—": "-", "−": "-", " ": " ", "　": " " };
  const NUM = "(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?";
  const SC_EN = { trillion: 1e6, billion: 1000, bn: 1000, million: 1, mn: 1, m: 1 };
  const SC_ZH = { "万亿": 1e6, "亿": 100, "千万": 10, "百万": 1, "万": 0.01 };
  const DOWN = /down|decreas|declin|fell|dropped|下降|减少|下跌|下滑/i;

  function norm(s) { return s.replace(/[（），；：％－–—− 　]/g, (c) => PUNCT[c] || c); }
  function numval(s) { const t = s.replace(/,/g, ""); const dec = t.includes(".") ? t.split(".")[1].length : 0; return [parseFloat(t), dec]; }
  function overlap(a, ha, b, hb) {
    const lo = Math.max(a - ha, b - hb), hi = Math.min(a + ha, b + hb);
    const eps = 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
    return hi - lo > eps;
  }

  function parseNumbers(t, lang) {
    const out = [], used = [];
    const free = (s, e) => used.every(([a, b]) => e <= a || s >= b);
    const add = (n) => { out.push(n); used.push([n.start, n.end]); };
    let re, m;
    if (lang === "en") {
      re = new RegExp("(RMB|HKD|USD|US\\$)\\s?(" + NUM + ")(?:\\s?(trillion|billion|million|bn|mn)(?![A-Za-z]))?", "gi");
      while ((m = re.exec(t))) {
        const [v, dec] = numval(m[2]); const cur = m[1].toUpperCase().replace("US$", "USD");
        const f = m[3] ? SC_EN[m[3].toLowerCase()] : null;
        add({ cls: f ? cur : cur + "1", value: f ? v * f : v, half: 0.5 * Math.pow(10, -dec) * (f || 1), raw: m[0], start: m.index, end: m.index + m[0].length });
      }
    } else {
      re = new RegExp("(人民币|港币|美元)?\\s?(" + NUM + ")\\s?(万亿|亿|千万|百万|万)?\\s?(元|港元|美元)", "g");
      while ((m = re.exec(t))) {
        if (!m[1] && !m[3] && /^\d$/.test(m[2])) continue;
        const [v, dec] = numval(m[2]);
        let cur = m[4] === "港元" || m[1] === "港币" ? "HKD" : m[4] === "美元" || m[1] === "美元" ? "USD" : "RMB";
        const f = m[3] ? SC_ZH[m[3]] : null;
        add({ cls: f ? cur : cur + "1", value: f ? v * f : v, half: 0.5 * Math.pow(10, -dec) * (f || 1), raw: m[0], start: m.index, end: m.index + m[0].length });
      }
    }
    re = /(?<![A-Za-z0-9_.])([+\-])?(\d+(?:\.\d+)?)\s?%/g;
    while ((m = re.exec(t))) {
      if (!free(m.index, m.index + m[0].length)) continue;
      const [v, dec] = numval(m[2]);
      add({ cls: "pct", value: m[1] === "-" ? -v : v, half: 0.5 * Math.pow(10, -dec), raw: m[0], start: m.index, end: m.index + m[0].length });
    }
    re = lang === "en" ? new RegExp("(?<![\\w.])(" + NUM + ")\\s?(billion|million|m)(?![A-Za-z])", "gi")
                       : new RegExp("(?<![\\d.])(" + NUM + ")\\s?(亿|万)(?!\\s?(?:元|港元|美元))", "g");
    while ((m = re.exec(t))) {
      if (!free(m.index, m.index + m[0].length)) continue;
      const [v, dec] = numval(m[1]); const f = lang === "en" ? SC_EN[m[2].toLowerCase()] : SC_ZH[m[2]];
      add({ cls: "count", value: v * f, half: 0.5 * Math.pow(10, -dec) * f, raw: m[0], start: m.index, end: m.index + m[0].length });
    }
    return out.sort((a, b) => a.start - b.start);
  }

  function parseGrowths(t, lang) {
    const out = []; let m;
    if (lang === "en") {
      const re = /(up|down|increased by|decreased by|increased|decreased|rose by|rose|grew by|grew|declined by|declined|fell by|fell)\s+(?:approximately\s|over\s|more than\s)?(\d+(?:\.\d+)?)\s?%/gi;
      while ((m = re.exec(t))) {
        const [v, dec] = numval(m[2]); const tail = t.slice(m.index + m[0].length, m.index + m[0].length + 60);
        out.push({ kind: /^[^.;]*?(quarter-on-quarter|QoQ|previous quarter)/i.test(tail) ? "qoq" : "yoy", value: DOWN.test(m[1]) ? -v : v, half: 0.5 * Math.pow(10, -dec), start: m.index, end: m.index + m[0].length, raw: m[0] });
      }
      const re2 = /(?<![\w.])([+\-])(\d+(?:\.\d+)?)\s?%\s?(YoY|QoQ)/gi;
      while ((m = re2.exec(t))) {
        const [v, dec] = numval(m[2]);
        out.push({ kind: m[3].toLowerCase(), value: m[1] === "-" ? -v : v, half: 0.5 * Math.pow(10, -dec), start: m.index, end: m.index + m[0].length, raw: m[0] });
      }
    } else {
      const re = /(同比|环比)?\s?(增长|增加|上升|提升|下降|减少|下跌|下滑)\s?(?:了\s?)?(?:超过|逾|约|近)?\s?(\d+(?:\.\d+)?)\s?%/g;
      while ((m = re.exec(t))) {
        const [v, dec] = numval(m[3]); const pre = t.slice(Math.max(0, m.index - 10), m.index);
        const kind = m[1] ? (m[1] === "环比" ? "qoq" : "yoy") : (pre.includes("环比") ? "qoq" : "yoy");
        out.push({ kind, value: DOWN.test(m[2]) ? -v : v, half: 0.5 * Math.pow(10, -dec), start: m.index, end: m.index + m[0].length, raw: m[0] });
      }
    }
    return out.sort((a, b) => a.start - b.start);
  }

  function compileRegistry(reg) {
    if (reg._compiled) return reg._compiled;
    const mets = reg.metrics.map((x) => ({
      x,
      en: (x.aliases_en || []).map((s) => { try { return new RegExp(s, "gi"); } catch (e) { return null; } }).filter(Boolean),
      zh: (x.aliases_zh || []).map((s) => { try { return new RegExp(s, "g"); } catch (e) { return null; } }).filter(Boolean),
    }));
    const byId = {}; reg.metrics.forEach((x) => (byId[x.id] = x));
    reg._compiled = { mets, byId };
    return reg._compiled;
  }

  function fmt(x) {
    if (x.cls === "RMB") return Math.abs(x.value) >= 1000 ? (x.value / 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + " 亿元" : x.value + " 百万元";
    if (x.cls === "pct") return (Math.round(x.value * 100) / 100) + "%";
    if (x.cls === "count") return x.value.toLocaleString("en-US") + " 百万";
    return String(x.value);
  }

  function check(text, reg, lang) {
    const C = compileRegistry(reg);
    const t = norm(text);
    lang = lang || ((t.match(/[一-鿿]/g) || []).length > 5 ? "zh" : "en");
    const marks = [];
    let basis = null;
    const paras = t.split(/\n+/);
    let off = 0;
    for (const para of paras) {
      if (/^\W*On a non-IFRS\d? basis|^\W*按非国际财务报告准则\d?,/i.test(para)) basis = "nonifrs";
      else if (/^\W*On an IFRS basis|^\W*按国际财务报告准则/.test(para)) basis = "ifrs";
      else if (!/^\s*-\s/.test(para)) basis = null;
      const cut = lang === "en" ? /\.\s+(?=[A-Z"'(~\d])|;\s*/g : /[。;!]/g;
      let s = 0, mm; const clauses = [];
      while ((mm = cut.exec(para))) { clauses.push([s, mm.index + mm[0].length]); s = mm.index + mm[0].length; }
      if (s < para.length) clauses.push([s, para.length]);
      for (const [cs, ce] of clauses) {
        const cl = para.slice(cs, ce);
        if (/six months|first half|full year|上半年|六个月|全年/i.test(cl)) continue;
        const cands = [];
        for (const M of C.mets) for (const re of M[lang]) { re.lastIndex = 0; let a; while ((a = re.exec(cl))) { if (a[0].length) cands.push([a.index, a.index + a[0].length, M.x.id]); else re.lastIndex++; } }
        cands.sort((a, b) => a[0] - b[0] || (b[1] - b[0]) - (a[1] - a[0]));
        const sel = []; let last = -1;
        for (const c of cands) if (c[0] >= last) { sel.push(c); last = c[1]; }
        const nums = parseNumbers(cl, lang), grs = parseGrowths(cl, lang);
        sel.forEach(([a0, a1, id], i) => {
          const wend = i + 1 < sel.length ? sel[i + 1][0] : cl.length;
          const prefix = cl.slice(0, a0);
          if (reg.nonifrs_remap && reg.nonifrs_remap[id] && (basis === "nonifrs" || /non-IFRS[^.;]{0,25}$|非国际财务报告准则[^。;]{0,6}$|non-IFRS basis/i.test(prefix))) id = reg.nonifrs_remap[id];
          const x = C.byId[id]; if (!x) return;
          const money = ["RMB", "HKD", "USD", "RMB1"];
          const want = money.includes(x.cls) ? money.concat(["HKD1", "USD1"]) : [x.cls];
          const n = nums.find((n) => n.end > a1 && n.end <= wend && want.includes(n.cls));
          if (n) {
            const v = x.signed ? (/negative\s*$/i.test(prefix.slice(-14)) || /^\s?转负/.test(cl.slice(a1)) ? -Math.abs(n.value) : n.value) : Math.abs(n.value);
            const ok = n.cls === x.cls && overlap(v, n.half, x.value, x.half_tol);
            marks.push({ start: off + cs + n.start, end: off + cs + n.end, status: ok ? "ok" : "bad", metric: x.id, name: x.name_zh, kind: "value", found: n.raw, expected: fmt(x), msg: ok ? "与已披露一致" : "与已披露不符：应为 " + fmt(x) });
          }
          const g = grs.find((g) => g.start >= a1 && g.start < wend);
          if (g && x[g.kind]) {
            const r = x[g.kind];
            const ok = overlap(g.value, g.half, r.value, r.half_tol) && !(g.value * r.value < 0 && Math.abs(r.value) > r.half_tol);
            marks.push({ start: off + cs + g.start, end: off + cs + g.end, status: ok ? "ok" : "bad", metric: x.id, name: x.name_zh, kind: g.kind, found: g.raw, expected: (r.value > 0 ? "+" : "") + r.value + "%", msg: ok ? "同比/环比一致" : "同比/环比不符：应为 " + (r.value > 0 ? "+" : "") + r.value + "%" });
          }
        });
      }
      off += para.length + 1;
    }
    return marks;
  }

  const api = { check, parseNumbers, parseGrowths };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.M4Check = api;
})(typeof window !== "undefined" ? window : globalThis);
