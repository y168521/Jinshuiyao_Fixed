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

  function applySort(table, ths, idx, asc) {
    for (var k = 0; k < ths.length; k++) {
      var a = ths[k].lastChild;
      if (a && a.tagName === "SPAN") a.textContent = (k === idx ? (asc ? "▲" : "▼") : "");
    }
    var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
    rows.sort(function (r1, r2) {
      var c1 = r1.cells[idx], c2 = r2.cells[idx];
      var v1 = c1 ? cellValue(c1) : "", v2 = c2 ? cellValue(c2) : "";
      if (v1 === -Infinity) return 1;
      if (v2 === -Infinity) return -1;
      var cmp = (typeof v1 === "number" && typeof v2 === "number") ? (v1 - v2) : String(v1).localeCompare(String(v2), "zh-CN");
      return asc ? cmp : -cmp;
    });
    var tbody = table.querySelector("tbody");
    for (var r = 0; r < rows.length; r++) tbody.appendChild(rows[r]);
  }

  function sortKey(table) { return table.id ? "jsy_sort_" + table.id : null; }
  function loadSort(table) {
    if (!table.id) return null;
    try {
      var raw = localStorage.getItem(sortKey(table));
      if (raw) { var d = JSON.parse(raw); if (typeof d.c === "number" && d.a !== undefined) return d; }
    } catch (e) {}
    return null;
  }
  function saveSort(table, idx, asc) {
    if (!table.id) return;
    try { localStorage.setItem(sortKey(table), JSON.stringify({ c: idx, a: asc })); } catch (e) {}
  }

  window.enhanceTable = function (table, opts) {
    if (!table) return;
    opts = opts || {};
    var state = { key: -1, asc: true, page: 1, q: "" };
    var pageSize = opts.pageSize || 20;
    var thead = table.querySelector("thead");
    if (!thead) return;
    var ths = thead.querySelectorAll("th");
    var filterWrap = null, filterInp = null, hintEl = null, pagerEl = null, rowsCache = null;

    function visibleRows() {
      if (!rowsCache || rowsCache.length !== table.querySelectorAll("tbody tr").length) {
        rowsCache = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
      }
      return rowsCache;
    }

    function render() {
      var rows = visibleRows();
      var q = state.q;
      var matched = [];
      for (var i = 0; i < rows.length; i++) {
        var hit = !q || (rows[i].textContent || "").toLowerCase().indexOf(q) > -1;
        rows[i].style.display = "none";
        if (hit) matched.push(rows[i]);
      }
      if (opts.pagination && matched.length > pageSize) {
        var total = matched.length;
        var pages = Math.ceil(total / pageSize);
        if (state.page > pages) state.page = pages;
        if (state.page < 1) state.page = 1;
        var from = (state.page - 1) * pageSize;
        var to = Math.min(from + pageSize, total);
        for (var p = from; p < to; p++) matched[p].style.display = "";
        if (pagerEl) pagerEl.innerHTML = pagerHtml(state.page, pages, total);
      } else {
        state.page = 1;
        for (var m = 0; m < matched.length; m++) matched[m].style.display = "";
        if (pagerEl) pagerEl.innerHTML = "";
      }
      if (hintEl) hintEl.textContent = q ? "匹配 " + matched.length + " / " + rows.length + " 行" : "";
    }

    function pagerHtml(page, pages, total) {
      var bstyle = 'style="margin-left:8px;padding:3px 12px;border-radius:6px;border:1px solid rgba(201,169,110,.35);background:transparent;color:#D8DEE9;font-size:12px;cursor:pointer;"';
      var h = '<span style="color:var(--muted);font-size:12px;">共 ' + total + ' 条 · 第 ' + page + ' / ' + pages + ' 页</span> ';
      h += '<button type="button" data-pg="prev" ' + bstyle + '>‹ 上一页</button>';
      h += '<button type="button" data-pg="next" ' + bstyle + '>下一页 ›</button>';
      return h;
    }

    for (var i = 0; i < ths.length; i++) {
      (function (idx, th) {
        th.style.cursor = "pointer";
        th.title = "点击排序";
        var arrow = document.createElement("span");
        arrow.style.cssText = "font-size:10px;margin-left:3px;opacity:.7";
        th.appendChild(arrow);
        th.addEventListener("click", function () {
          if (state.key === idx) { state.asc = !state.asc; } else { state.key = idx; state.asc = true; }
          applySort(table, ths, idx, state.asc);
          saveSort(table, idx, state.asc);
          rowsCache = null;
          render();
        });
      })(i, ths[i]);
    }
    if (opts.sticky !== false) {
      var bg = getComputedStyle(ths[0]).backgroundColor;
      if (!bg || bg === "rgba(0, 0, 0, 0)") bg = "#0F2238";
      for (var s = 0; s < ths.length; s++) {
        ths[s].style.position = "sticky";
        ths[s].style.top = "0";
        ths[s].style.zIndex = "5";
        ths[s].style.backgroundColor = bg;
      }
    }
    if (opts.filter) {
      filterWrap = table.previousElementSibling;
      if (!(filterWrap && filterWrap.className === "jsy-table-filter")) {
        filterWrap = document.createElement("div");
        filterWrap.className = "jsy-table-filter";
        filterWrap.style.cssText = "margin-bottom:8px;position:relative;";
        filterInp = document.createElement("input");
        filterInp.type = "text";
        filterInp.placeholder = "🔍 输入关键字过滤（支持表内任意列，不区分大小写）";
        filterInp.style.cssText = "width:100%;padding:6px 10px;border-radius:6px;border:1px solid rgba(201,169,110,.35);background:rgba(0,0,0,.25);color:inherit;font-size:12px;";
        hintEl = document.createElement("div");
        hintEl.className = "jsy-filter-hint";
        hintEl.style.cssText = "position:absolute;right:8px;top:7px;font-size:11px;color:rgba(232,236,241,.4);pointer-events:none;";
        filterInp.addEventListener("input", function () {
          state.q = filterInp.value.trim().toLowerCase();
          state.page = 1;
          render();
        });
        filterWrap.appendChild(filterInp);
        filterWrap.appendChild(hintEl);
        table.parentNode.insertBefore(filterWrap, table);
      } else {
        filterInp = filterWrap.querySelector("input");
        hintEl = filterWrap.querySelector(".jsy-filter-hint");
      }
    }
    if (opts.pagination) {
      pagerEl = table.nextElementSibling;
      if (!(pagerEl && pagerEl.className === "jsy-pager")) {
        pagerEl = document.createElement("div");
        pagerEl.className = "jsy-pager";
        pagerEl.style.cssText = "margin-top:8px;text-align:right;font-size:12px;";
        pagerEl.addEventListener("click", function (e) {
          var btn = e.target;
          if (!btn || !btn.getAttribute || !btn.getAttribute("data-pg")) return;
          if (btn.getAttribute("data-pg") === "prev" && state.page > 1) state.page--;
          if (btn.getAttribute("data-pg") === "next") state.page++;
          render();
        });
        table.parentNode.insertBefore(pagerEl, table.nextSibling);
      }
    }
    var remembered = loadSort(table);
    if (remembered && remembered.c < ths.length) {
      state.key = remembered.c; state.asc = !!remembered.a;
      applySort(table, ths, remembered.c, state.asc);
      rowsCache = null;
    }
    render();
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
