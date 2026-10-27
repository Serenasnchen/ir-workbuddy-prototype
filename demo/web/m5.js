/* Panel 6: 评测与回放 — T1–T8 scoreboard with honest statuses, per-module run trace, integrity statement */
(function () {
  "use strict";
  const ST = { "通过": "ok",  "已标注": "infer", "未达门槛": "warn", "未执行": "warn" };
  function render() {
    const { D, esc, fmt } = window.IR;
    const host = document.getElementById("eval");
    const M = D.m5_eval;
    if (!M) { host.innerHTML = `<p class="sub">本模块数据尚未生成。</p>`; return; }
    const pass = M.scoreboard.filter((r) => r.status === "通过").length;
    let h = `<h2 class="lede">用评测而不是宣称来决定是否推广：8 项测试，${pass} 项通过，其余如实标注</h2>`;
    h += `<p class="sub">门槛为试点建议值；未达门槛或未执行的测试，意味着对应场景上线前必须保留人工复核或补做测试。</p>`;
    h += `<div class="block"><table class="t"><thead><tr><th>编号</th><th>测什么</th><th>指标</th><th>实测</th><th>门槛</th><th>状态</th></tr></thead><tbody>`
      + M.scoreboard.map((r) => `<tr><td><b>${esc(r.id)}</b></td><td>${esc(r.test)}</td><td>${esc(r.metric)}</td><td>${esc(r.value)}<div style="color:var(--muted);font-size:12px">${esc(r.note || "")}</div></td><td>${esc(r.threshold)}</td><td><span class="tag ${ST[r.status] || "infer"}">${esc(r.status)}</span></td></tr>`).join("")
      + `</tbody></table></div>`;
    h += `<div class="grid-2"><div class="block"><h3>运行回放</h3><p class="hint">每个模块都由脚本从本地文件重建；输入文件逐一记录 SHA-256，重跑结果一致。</p><table class="t"><thead><tr><th>模块</th><th>产物类型</th><th>脚本</th><th class="n">输入文件</th><th>网络</th><th>自检</th></tr></thead><tbody>`
      + M.trace.map((t) => `<tr><td><b>${esc(t.module)}</b></td><td>${esc(t.generated_by)}</td><td style="font-size:12px">${esc(t.script)}</td><td class="n">${t.inputs}</td><td style="font-size:12px">${esc(netText(t.network))}</td><td><span class="tag ${/^通过|通过（/.test(t.self_check) ? "ok" : "infer"}">${esc(t.self_check)}</span></td></tr>`).join("")
      + `</tbody></table></div>`;
    h += `<div class="block"><h3>诚信声明</h3><ul style="padding-left:18px;margin:0">${M.integrity.map((x) => `<li style="margin-bottom:8px">${esc(x)}</li>`).join("")}</ul></div></div>`;
    host.innerHTML = h;
    host.dataset.trace = `<span><span class="kind">${esc(M.meta.generated_by)}</span>｜${esc(M.meta.script)}｜截至 ${esc(M.meta.as_of)}</span>`;
  }
  function netText(n) {
    if (!n || !Object.keys(n).length) return "—";
    const parts = [];
    if (n.get != null) parts.push(`GET ${n.get}`);
    if (n.post != null) parts.push(`POST ${n.post}`);
    if (n.cache_hits != null) parts.push(`缓存 ${n.cache_hits}`);
    return parts.join("，") || "已缓存";
  }
  render.panelId = "eval";
  (window.IR_RENDERERS = window.IR_RENDERERS || []).push(render);
})();
