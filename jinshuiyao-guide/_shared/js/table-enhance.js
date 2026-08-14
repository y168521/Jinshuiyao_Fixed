/* 金水谣表格增强：点击表头排序 + CSV 导出。
   用法：
   - window.enhanceTable(tableEl) —— 表头点击排序（数值/字符串自动识别，再点翻转，默认升序）
   - window.exportTableCsv(tableEl, filename) —— 导出当前表格为 CSV（含 BOM，Excel 直接打开不乱码）
   纯原生 JS，无依赖；排序只改 DOM 行序，不动数据源。 */
(function () {
  "use strict";

  function cellValue(td) {
    var t = (td.textContent || "").trim();
    var cleaned = t.replace(/[%,期天元万，\s]/g, "");
    var n = parseFloat(cleaned);
    if (!isNaN(n) && /^\d+(\.\d+)?$/.test(cleaned)) return n;
    if (t === "—" || t === "-") return -Infinity;
    return t;
  }

  window.enhanceTable = function (table, opts) {
    if (!table) return;
    var state = { key: -1, asc: true };
    var thead = table.querySelector("thead");
    if (!thead) return;
    var ths = thead.querySelectorAll("th");
    for (var i = 0; i < ths.length; i++) {
      (function (idx, th) {
        th.style.cursor = "pointer";
        th.title = "点击排序";
        var arrow = document.createElement("span");
        arrow.style.cssText = "font-size:10px;margin-left:3px;opacity:.7";
        th.appendChild(arrow);
        th.addEventListener("click", function () {
          if (state.key === idx) { state.asc = !state.asc; } else { state.key = idx; state.asc = true; }
          for (var k = 0; k < ths.length; k++) {
            var a = ths[k].lastChild;
            if (a && a.tagName === "SPAN") a.textContent = (k === idx ? (state.asc ? "▲" : "▼") : "");
          }
          var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
          rows.sort(function (r1, r2) {
            var c1 = r1.cells[idx], c2 = r2.cells[idx];
            var v1 = c1 ? cellValue(c1) : "", v2 = c2 ? cellValue(c2) : "";
            if (v1 === -Infinity) return 1;
            if (v2 === -Infinity) return -1;
            var cmp = (typeof v1 === "number" && typeof v2 === "number") ? (v1 - v2) : String(v1).localeCompare(String(v2), "zh-CN");
            return state.asc ? cmp : -cmp;
          });
          var tbody = table.querySelector("tbody");
          for (var r = 0; r < rows.length; r++) tbody.appendChild(rows[r]);
        });
      })(i, ths[i]);
    }
  };

  function esc(v) {
    v = String(v == null ? "" : v);
    if (/[",\n]/.test(v)) return '"' + v.replace(/"/g, '""') + '"';
    return v;
  }

  window.exportTableCsv = function (table, filename) {
    if (!table) return;
    var lines = [];
    var rows = table.querySelectorAll("thead tr, tbody tr");
    for (var i = 0; i < rows.length; i++) {
      var cells = rows[i].querySelectorAll("th, td");
      var line = [];
      for (var j = 0; j < cells.length; j++) line.push(esc(cells[j].textContent));
      lines.push(line.join(","));
    }
    var csv = "\ufeff" + lines.join("\r\n");
    var blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "export.csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  };
})();
