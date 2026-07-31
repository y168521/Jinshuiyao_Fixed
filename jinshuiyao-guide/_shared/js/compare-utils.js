/* 金水谣 · 通用对比表格工具：渲染「技术方案 / 选项对比」表，支持文本筛选 + 维度排序。
   纯原生 JS，无依赖。被 compare-tech.html 等页面复用。
   用法：
     CompareUtils.mount(containerEl, data, { filter:true, sortable:true });
   data 结构见 jinshuiyao-guide/data/tech-solutions.json。 */
(function (global) {
  "use strict";

  /* ---- 自注入样式（保证本工具自包含、可跨页复用） ---- */
  var CSS =
    ".cu-app{max-width:1200px;margin:0 auto;padding:1.5rem 1.5rem 3rem}" +
    ".cu-head{margin-bottom:1rem}" +
    ".cu-head h2{color:#C9A96E;font-size:1.5rem;margin-bottom:.4rem}" +
    ".cu-head p{color:rgba(232,236,241,.7);font-size:.9rem;margin:.2rem 0}" +
    ".cu-updated{color:rgba(232,236,241,.45)!important;font-size:.8rem!important}" +
    ".cu-filter{margin:.8rem 0 1rem}" +
    ".cu-filter input{width:100%;max-width:420px;padding:.6rem .9rem;border-radius:10px;" +
    "border:1px solid rgba(201,169,110,.3);background:rgba(11,26,47,.6);color:#E8ECF1;font-size:.95rem;outline:none}" +
    ".cu-filter input:focus{border-color:#5BC0DE;box-shadow:0 0 0 3px rgba(91,192,222,.15)}" +
    ".cu-table{width:100%;border-collapse:collapse;font-size:.88rem;background:rgba(13,31,53,.5);" +
    "border-radius:12px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.25)}" +
    ".cu-table th,.cu-table td{padding:.7rem .8rem;text-align:left;vertical-align:top;border-bottom:1px solid rgba(201,169,110,.12)}" +
    ".cu-table thead th{background:rgba(201,169,110,.1);color:#C9A96E;font-weight:700;position:sticky;top:0;cursor:default;user-select:none}" +
    ".cu-table thead th[data-sort]{cursor:pointer}" +
    ".cu-table thead th[data-sort]:hover{color:#E8ECF1}" +
    ".cu-table thead th.cu-active{color:#5BC0DE}" +
    ".cu-table tbody tr:hover{background:rgba(91,192,222,.06)}" +
    ".cu-name b{color:#E8ECF1;font-size:.95rem}" +
    ".cu-cat{display:inline-block;margin-left:.5rem;font-size:.72rem;color:#5BC0DE;" +
    "background:rgba(91,192,222,.12);padding:.1rem .5rem;border-radius:999px}" +
    ".cu-sum{color:rgba(232,236,241,.6);font-size:.8rem;margin-top:.3rem;max-width:280px}" +
    ".cu-ref{display:inline-block;margin-top:.3rem;font-size:.78rem;color:#5BC0DE}" +
    ".cu-comp b{font-size:1.05rem;color:#C9A96E}" +
    ".cu-bar{position:relative;height:18px;background:rgba(11,26,47,.6);border-radius:6px;overflow:hidden;min-width:64px}" +
    ".cu-bar span{position:absolute;left:0;top:0;bottom:0;display:block;border-radius:6px}" +
    ".cu-bar b{position:relative;z-index:1;display:block;text-align:center;line-height:18px;font-size:.72rem;color:#0B1A2F;font-weight:700}" +
    ".cu-list{margin:0;padding-left:1rem;color:rgba(232,236,241,.75)}" +
    ".cu-list li{margin:.15rem 0}" +
    ".cu-tag{display:inline-block;margin:.1rem .25rem .1rem 0;font-size:.72rem;color:#C9A96E;" +
    "background:rgba(201,169,110,.12);border:1px solid rgba(201,169,110,.25);padding:.1rem .5rem;border-radius:999px}" +
    ".cu-empty{text-align:center;color:rgba(232,236,241,.5);padding:2rem}" +
    ".cu-error{color:#C8755A;background:rgba(200,117,90,.1);border:1px solid rgba(200,117,90,.3);" +
    "padding:1rem 1.2rem;border-radius:10px;line-height:1.7}";
  var _style = document.createElement("style");
  _style.textContent = CSS;
  document.head.appendChild(_style);

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // 加权综合分（1-5，与单维同标度）
  function composite(scores, dims) {
    var total = 0, wsum = 0;
    dims.forEach(function (d) {
      var v = scores ? scores[d.key] : undefined;
      if (typeof v === "number") { total += v * (d.weight || 0); wsum += (d.weight || 0); }
    });
    return wsum ? (total / wsum) : 0;
  }

  function scoreCell(v) {
    v = Number(v) || 0;
    var pct = Math.max(0, Math.min(100, (v / 5) * 100));
    var hue = Math.round(120 - (pct * 1.2)); // 红(0)->绿(100)
    return '<div class="cu-bar"><span style="width:' + pct + "%;background:hsl(" + hue + ',55%,48%)"></span>' +
      "<b>" + v.toFixed(1) + "</b></div>";
  }

  function tagsCell(arr) {
    return (arr || []).map(function (t) { return '<span class="cu-tag">' + esc(t) + "</span>"; }).join("");
  }

  function listCell(arr) {
    if (!arr || !arr.length) return '<span style="color:rgba(232,236,241,.35)">—</span>';
    return "<ul class='cu-list'>" + arr.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
  }

  function mount(root, data, opts) {
    opts = opts || {};
    root.innerHTML = "";
    var meta = data.meta || {};
    var dims = data.dimensions || [];
    var rows = (data.solutions || []).slice();

    var head = document.createElement("div");
    head.className = "cu-head";
    head.innerHTML = "<h2>" + esc(meta.title || "方案对比") + "</h2>" +
      (meta.description ? "<p>" + esc(meta.description) + "</p>" : "") +
      (meta.updated ? "<p class='cu-updated'>更新：" + esc(meta.updated) + "</p>" : "");
    root.appendChild(head);

    var filterInput = null;
    if (opts.filter !== false) {
      var fw = document.createElement("div");
      fw.className = "cu-filter";
      fw.innerHTML = "<input type='search' placeholder='筛选方案 / 标签 / 关键词…' />";
      root.appendChild(fw);
      filterInput = fw.querySelector("input");
    }

    var table = document.createElement("table");
    table.className = "cu-table";
    root.appendChild(table);

    var sortKey = null, sortDir = 1;

    function rowMatches(row, q) {
      if (!q) return true;
      q = q.toLowerCase();
      var hay = [row.name, row.category, row.summary, (row.tags || []).join(" "),
        (row.pros || []).join(" "), (row.cons || []).join(" ")].join(" ").toLowerCase();
      return hay.indexOf(q) >= 0;
    }

    function render() {
      var q = filterInput ? filterInput.value.trim() : "";
      var view = rows.filter(function (r) { return rowMatches(r, q); });
      if (sortKey) {
        view.sort(function (a, b) {
          var av = sortKey === "__composite__" ? composite(a.scores, dims) : (a.scores && a.scores[sortKey]);
          var bv = sortKey === "__composite__" ? composite(b.scores, dims) : (b.scores && b.scores[sortKey]);
          return ((av || 0) - (bv || 0)) * sortDir;
        });
      }
      var thead = "<thead><tr><th class='cu-name'>方案</th>" +
        "<th data-sort='__composite__' class='" + (sortKey === "__composite__" ? "cu-active" : "") + "'>综合" +
        (sortKey === "__composite__" ? (sortDir > 0 ? " ▲" : " ▼") : "") + "</th>";
      dims.forEach(function (d) {
        thead += "<th data-sort='" + d.key + "' class='" + (sortKey === d.key ? "cu-active" : "") + "'>" + esc(d.label) +
          (sortKey === d.key ? (sortDir > 0 ? " ▲" : " ▼") : "") + "</th>";
      });
      thead += "<th>优势</th><th>劣势</th><th>标签</th></tr></thead>";

      var tbody = "<tbody>";
      if (!view.length) {
        tbody += "<tr><td colspan='" + (dims.length + 5) + "' class='cu-empty'>没有匹配的方案</td></tr>";
      }
      view.forEach(function (r) {
        tbody += "<tr><td class='cu-name'><b>" + esc(r.name) + "</b>" +
          (r.category ? "<span class='cu-cat'>" + esc(r.category) + "</span>" : "") +
          (r.summary ? "<div class='cu-sum'>" + esc(r.summary) + "</div>" : "") +
          (r.reference ? "<a class='cu-ref' href='" + esc(r.reference) + "' target='_blank' rel='noopener'>参考 ↗</a>" : "") + "</td>";
        tbody += "<td class='cu-comp'>" + scoreCell(composite(r.scores, dims)) + "</td>";
        dims.forEach(function (d) {
          tbody += "<td>" + scoreCell((r.scores && r.scores[d.key]) || 0) + "</td>";
        });
        tbody += "<td>" + listCell(r.pros) + "</td><td>" + listCell(r.cons) + "</td><td>" + tagsCell(r.tags) + "</td></tr>";
      });
      tbody += "</tbody>";
      table.innerHTML = thead + tbody;
    }

    render();

    if (filterInput) filterInput.addEventListener("input", render);
    table.addEventListener("click", function (e) {
      var th = e.target.closest("th[data-sort]");
      if (!th) return;
      var k = th.getAttribute("data-sort");
      if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = -1; }
      render();
    });
  }

  global.CompareUtils = { mount: mount, composite: composite };
})(window);
