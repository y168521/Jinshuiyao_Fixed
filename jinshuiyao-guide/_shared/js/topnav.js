/* 金水谣统一顶栏：被所有子页面引用，提供"随时返回工作台 / 门户"的导航。
   两种模式：
   - 默认（bar）：通栏吸顶，适合普通文档页；
   - data-nav="float"（写在 <body> 上）：右上角悬浮胶囊，适合全屏对话类应用（如 AI助手），不破坏布局。
   新增：健康状态指示器（绿/黄/红点）+ 自动重试安全请求工具 safeFetch()。
   纯原生 JS，无任何依赖。 */
(function () {
  "use strict";
  /* ====== 全站 favicon（W63补99 / JS-20260816-04）：SVG 金字数据图标，无需 .ico 文件 ====== */
  if (!document.querySelector('link[rel="icon"]')) {
    var icon = document.createElement('link');
    icon.rel = 'icon';
    icon.type = 'image/svg+xml';
    icon.href = 'data:image/svg+xml,' + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
      '<rect width="64" height="64" rx="14" fill="#0B1A2F"/>' +
      '<circle cx="24" cy="26" r="9" fill="#C8785A"/>' +
      '<circle cx="42" cy="26" r="9" fill="#C9A96E"/>' +
      '<circle cx="18" cy="44" r="8" fill="#2D8B7E"/>' +
      '<circle cx="34" cy="44" r="8" fill="#C9A96E"/>' +
      '<circle cx="50" cy="44" r="8" fill="#5BC0DE"/>' +
      '</svg>');
    document.head.appendChild(icon);
  }
  var mode = (document.body && document.body.getAttribute("data-nav")) || "";
  if (!mode) {
    var p = location.pathname || "";
    mode = (p === "/ai-agent" || p === "/ai-test") ? "float" : "bar";
  }
  var HOME = "/workbench";
  var PORTAL = "/";

  /* ====== 主题切换（P0-5 · 2026-09-23）======
     三档：金水谣七色(L2 owner 默认) / 浅色(L0) / 深色(L0)。
     优先级：localStorage 自选 > 不变（默认 L2）。
     持久化只落本机 localStorage —— 后端 /api/theme 是 user_id 维度（面向未来
     多用户 L1 自选），单人自用场景无需走服务端，避免与 theme_manager 双写冲突。
     越早应用越能减少闪白，所以放在建 DOM 之前。 */
  var THEME_CYCLE = [
    { key: "", label: "七色", title: "金水谣七色（个人默认）" },
    { key: "system-light", label: "浅色", title: "系统默认 · 浅色中性" },
    { key: "system-dark", label: "深色", title: "系统默认 · 深色中性" }
  ];
  function readTheme() {
    try { return localStorage.getItem("jsy-theme") || ""; } catch (e) { return ""; }
  }
  function applyTheme(key) {
    key = key || "";
    var el = document.documentElement;
    if (key) { el.setAttribute("data-theme", key); } else { el.removeAttribute("data-theme"); }
    try { localStorage.setItem("jsy-theme", key); } catch (e) { /* 隐私模式下忽略 */ }
    var meta = THEME_CYCLE[0];
    for (var i = 0; i < THEME_CYCLE.length; i++) { if (THEME_CYCLE[i].key === key) { meta = THEME_CYCLE[i]; } }
    var btn = document.getElementById("tsThemeBtn");
    if (btn) {
      btn.textContent = meta.label;
      btn.setAttribute("aria-label", "切换主题（当前：" + meta.title + "）");
      btn.title = "切换主题（当前：" + meta.title + "）";
    }
  }
  function nextTheme() {
    var cur = readTheme();
    for (var i = 0; i < THEME_CYCLE.length; i++) {
      if (THEME_CYCLE[i].key === cur) { return THEME_CYCLE[(i + 1) % THEME_CYCLE.length].key; }
    }
    return THEME_CYCLE[1].key;
  }
  applyTheme(readTheme());

  /* ====== 健康状态指示器 ====== */
  var _healthStatus = "unknown"; // unknown | ok | degraded | error
  var _healthDetail = "";
  var _syncHintLoaded = false;

  function fetchSyncTime() {
    if (_syncHintLoaded) return;
    var xhr = new XMLHttpRequest();
    xhr.timeout = 6000;
    xhr.open("GET", "/api/automation-status?t=" + Date.now(), true);
    xhr.onload = function () {
      try {
        if (xhr.status !== 200) return;
        var d = JSON.parse(xhr.responseText);
        var t = d.auto_sync && d.auto_sync.last_run;
        if (!t) return;
        _syncHintLoaded = true;
        var dot = document.getElementById("ts-health-dot");
        if (!dot) return;
        var txt = String(t).replace("T", " ").slice(0, 19);
        dot.title = (dot.title ? dot.title + "\n" : "") + "自动同步最近：" + txt;
      } catch (e) { /* 静默失败，下次再试 */ }
    };
    xhr.send(null);
  }

  function updateHealthDot(status, detail) {
    _healthStatus = status || "unknown";
    _healthDetail = detail || "";
    var dot = document.getElementById("ts-health-dot");
    if (!dot) return;
    /* P0-5：状态色改走变量（带原值回退），随主题换肤 */
    var colors = { ok: "var(--jade,#2D8B7E)", degraded: "var(--gold,#C9A96E)",
                   error: "var(--copper,#C8755A)", unknown: "var(--idle,rgba(11,26,47,.4))" };
    dot.style.backgroundColor = colors[status] || colors.unknown;
    dot.title = status === "ok"
      ? "服务器运行正常"
      : "服务器状态: " + status + (detail ? "\n" + detail : "");
    if (status === "ok") fetchSyncTime();
  }

  function pollHealth() {
    var xhr = new XMLHttpRequest();
    xhr.timeout = 8000;
    xhr.open("GET", "/health?t=" + Date.now(), true);
    xhr.onload = function () {
      try {
        if (xhr.status === 200) {
          var d = JSON.parse(xhr.responseText);
          // 关键：旧版服务器没有 version 字段（或返回 {error:...}），一律判为「版本过旧」
          if (!d || d.error || !d.version) {
            updateHealthDot("error", "后端版本过旧，请双击「启动金水谣助手.bat」重启");
            return;
          }
          var errRate = d.error_rate || 0;
          var errs = d.errors_total || 0;
          if (errRate > 0.1 || errs > 5) {
            updateHealthDot("degraded", "错误率 " + (errRate * 100).toFixed(1) + "% (" + errs + "次)");
          } else {
            updateHealthDot("ok", "");
          }
        } else {
          updateHealthDot("error", "HTTP " + xhr.status);
        }
      } catch (e) {
        updateHealthDot("error", e.message);
      }
    };
    xhr.onerror = function () { updateHealthDot("error", "网络不通"); };
    xhr.ontimeout = function () { updateHealthDot("error", "响应超时"); };
    xhr.send(null);
  }

  /* ====== 安全请求（带自动重试） ====== */
  window.safeFetch = function (url, opts) {
    opts = opts || {};
    var retries = opts.retries || 2;
    var delay = opts.delay || 1000;
    var timeout = opts.timeout || 15000;

    return new Promise(function (resolve, reject) {
      var attempt = 0;
      function tryOnce() {
        attempt++;
        var xhr = new XMLHttpRequest();
        xhr.timeout = timeout;
        xhr.open((opts.method || "GET").toUpperCase(), url, true);

        // 设置 headers
        if (opts.headers) {
          for (var k in opts.headers) { if (opts.headers.hasOwnProperty(k)) xhr.setRequestHeader(k, opts.headers[k]); }
        }
        if (opts.contentType) { xhr.setRequestHeader("Content-Type", opts.contentType); }

        xhr.onload = function () {
          resolve({ status: xhr.status, text: xhr.responseText });
        };
        xhr.onerror = function () {
          if (attempt <= retries) {
            setTimeout(tryOnce, delay * attempt);
          } else {
            reject(new Error("请求失败(已重试" + retries + "次): " + url));
          }
        };
        xhr.ontimeout = function () {
          if (attempt <= retries) {
            setTimeout(tryOnce, delay * attempt);
          } else {
            reject(new Error("请求超时(已重试" + retries + "次): " + url));
          }
        };

        if (opts.body) { xhr.send(opts.body); }
        else { xhr.send(null); }
      }
      tryOnce();
    });
  };

  /* ====== 构建 DOM ====== */
  /* P0-5：顶栏配色改走 CSS 变量（带原值回退），随 data-theme 换肤；
     未引 theme.css 的页面靠回退值保持原外观，零回归。 */
  var css =
    ".ts-topnav{box-sizing:border-box;display:flex;align-items:center;gap:14px;" +
    "background:var(--deep,#0B1A2F);border-bottom:1px solid var(--gold-border,rgba(201,169,110,.18));padding:0 18px;height:52px;" +
    "font-family:var(--font,'Microsoft YaHei','PingFang SC','Noto Sans SC',system-ui,sans-serif);" +
    "z-index:99999;flex-shrink:0;backdrop-filter:blur(8px)}" +
    ".ts-topnav a{text-decoration:none;color:var(--ink-mid,rgba(232,236,241,.7));font-size:14px;font-weight:600;white-space:nowrap;transition:color .2s}" +
    ".ts-topnav a:hover{color:var(--gold,#C9A96E)}" +
    ".ts-topnav .ts-brand{color:var(--gold,#C9A96E);font-size:16px;font-weight:800;letter-spacing:.5px;display:flex;align-items:center;gap:8px}" +
    ".ts-topnav .ts-cur{color:var(--ink,#E8ECF1);font-size:14px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    /* 面包屑（P0-3）：全站唯一返回机制，替代原先 4 种并存的 back-link 写法 */
    ".ts-topnav .ts-crumbs{display:flex;align-items:center;min-width:0}" +
    ".ts-topnav .ts-crumbs ol{display:flex;align-items:center;gap:6px;list-style:none;margin:0;padding:0;min-width:0}" +
    ".ts-topnav .ts-crumbs li{display:flex;align-items:center;gap:6px;min-width:0}" +
    ".ts-topnav .ts-crumbs a{font-size:13px;font-weight:600;color:var(--ink-mid,rgba(232,236,241,.7));white-space:nowrap}" +
    ".ts-topnav .ts-crumbs a:hover{color:var(--gold,#C9A96E)}" +
    ".ts-topnav .ts-crumbs .ts-crumb-cur{font-size:13px;font-weight:700;color:var(--ink,#E8ECF1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    ".ts-topnav .ts-crumbs .ts-sep{font-size:12px;color:var(--ink-dim,rgba(232,236,241,.55))}" +
    "@media(max-width:640px){.ts-topnav .ts-crumbs .ts-crumb-prev{display:none}}" +
    ".ts-topnav .ts-subs{display:flex;align-items:center;gap:6px;margin-left:8px}" +
    ".ts-topnav .ts-sub{font-size:13px;font-weight:600;padding:4px 10px;border-radius:999px;border:1px solid var(--gold-border,rgba(201,169,110,.18));color:var(--ink-mid,rgba(232,236,241,.75));transition:all .2s}" +
    ".ts-topnav .ts-sub:hover{color:var(--gold,#C9A96E);border-color:var(--gold-border-strong,rgba(201,169,110,.5))}" +
    ".ts-topnav .ts-sub.on{color:var(--deep,#0B1A2F);background:var(--gold,#C9A96E);border-color:var(--gold,#C9A96E);font-weight:700}" +
    ".ts-topnav .ts-drop{position:relative}" +
    ".ts-topnav .ts-drop-btn,.ts-topnav .ts-theme-btn{background:transparent;border:1px solid var(--gold-border,rgba(201,169,110,.25));color:var(--gold,#C9A96E);font-size:13px;font-weight:600;font-family:inherit;padding:4px 10px;border-radius:999px;cursor:pointer;white-space:nowrap}" +
    ".ts-topnav .ts-drop-btn:hover,.ts-topnav .ts-theme-btn:hover{background:var(--gold-soft,rgba(201,169,110,.12))}" +
    ".ts-topnav .ts-drop-menu{display:none;position:absolute;top:calc(100% + 6px);right:0;min-width:150px;background:var(--card-bg,#0D2137);border:1px solid var(--gold-border,rgba(201,169,110,.25));border-radius:10px;box-shadow:var(--js-elev-2,0 8px 24px rgba(0,0,0,.5));padding:6px;z-index:99998}" +
    ".ts-topnav .ts-drop-menu a{display:block;padding:8px 12px;border-radius:6px;font-size:13px;color:var(--ink-mid,rgba(232,236,241,.8))}" +
    ".ts-topnav .ts-drop-menu a:hover{background:var(--gold-soft,rgba(201,169,110,.12));color:var(--gold,#C9A96E)}" +
    ".ts-topnav .ts-spacer{flex:1}" +
    ".ts-topnav .ts-pill{background:var(--gold-soft,rgba(201,169,110,.12));color:var(--gold,#C9A96E);padding:6px 12px;border-radius:999px;font-size:13px;border:1px solid var(--gold-border,rgba(201,169,110,.25))}" +
    ".ts-topnav.float{position:fixed;top:12px;right:12px;left:auto;width:auto;border:none;" +
    "background:var(--card-bg,rgba(13,31,53,.95));border-radius:999px;box-shadow:var(--js-elev-2,0 6px 20px rgba(0,0,0,.4));padding:8px 14px;height:auto;border:1px solid var(--gold-border,rgba(201,169,110,.18))}" +
    ".ts-topnav.float .ts-cur,.ts-topnav.float .ts-crumbs,.ts-topnav.float .ts-spacer{display:none}" +
    /* 健康指示灯 */
    ".ts-hdot{width:10px;height:10px;border-radius:50%;display:inline-block;flex-shrink:0;" +
    "transition:background-color .3s;box-shadow:0 0 6px rgba(0,0,0,.3)}";

  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ====== 面包屑（P0-3 · 2026-09-23）======
     全站唯一返回机制：原先并存 4 种 back-link 写法（.back / .back-link /
     绝对定位版 / 固定悬浮版），且 Hub 页统一跳"控制中心"而不是自己的领域，
     现已全部删除，改由面包屑承担。层级：首页 > 领域 Hub（或 系统）> 当前页。
     未登记的路由自动退化为「首页 > 页面标题」，不会没导航。 */
  var CRUMB_HUB = { "/lottery": "彩票", "/fund": "基金", "/stock": "股票", "/football": "足彩" };
  var CRUMB_SYS = {
    "/control-center": 1, "/health-check": 1, "/automation-dashboard": 1, "/automation-status": 1,
    "/scheduler": 1, "/scheduler-board": 1, "/engine-dashboard": 1, "/review-dashboard": 1,
    "/prediction-tracker": 1, "/daily-report": 1, "/changelog": 1, "/ai-usage": 1,
    "/system-tools": 1, "/sync": 1
  };
  var CRUMB_NAME = {
    "/workbench": "工作台", "/ai-agent": "AI 助手", "/ai-test": "AI 用例", "/smart-coder": "智能代码助手",
    "/knowledge-browser": "知识库", "/agent-pipeline": "AI 流水线", "/control-center": "总控台",
    "/sync": "跨设备看板", "/health-check": "体检中心", "/automation-dashboard": "自动化状态",
    "/automation-status": "自动化运行状态", "/scheduler": "定时任务", "/scheduler-board": "定时任务看板",
    "/engine-dashboard": "效果看板", "/review-dashboard": "审查仪表盘", "/prediction-tracker": "预测追踪",
    "/daily-report": "大脑日报", "/changelog": "更新日志", "/ai-usage": "AI 用量", "/system-tools": "系统工具箱",
    "/docs": "接口文档", "/test-report": "测试报告", "/architecture": "体系架构", "/global-plan": "全局规划",
    "/chain-map": "链路地图", "/compare-tech": "方案对比", "/jinshuiyao-guide": "导航指南", "/showcase": "组件库",
    "/route": "任务调度中枢", "/math-model": "数学模型", "/prediction-reference": "预测参考",
    "/dashboard": "足彩模拟大盘", "/trend": "走势图", "/quant": "量化盘", "/gap-analysis": "差距分析",
    "/deepseek-manual": "DeepSeek 备用", "/daily-sentiment": "A股情绪日报",
    "/lottery/dashboard": "仪表盘", "/lottery/sources-health": "数据源健康", "/lottery/omission-heatmap": "遗漏热力图",
    "/lottery/omission-table": "遗漏表格", "/lottery/hot-rank": "冷热排行", "/lottery/filter-panel": "缩水过滤",
    "/lottery/rotation-matrix": "旋转矩阵", "/lottery/prize-calculator": "奖金计算器",
    "/lottery/head-tail-analysis": "龙头凤尾", "/lottery/historical-same-period": "历史同期",
    "/lottery/number-follow-up": "号码跟随", "/lottery/trend-classification": "走势分类",
    "/lottery/ac-calculator": "AC 值", "/lottery/combo-calculator": "组合计算", "/lottery/audit-dashboard": "操作留痕",
    "/fund/dashboard": "仪表盘", "/fund/nav-trend": "净值走势", "/fund/holdings": "持仓分析",
    "/fund/screener": "基金筛选", "/fund/detail": "基金详情", "/fund/dca": "定投模拟", "/fund/portfolio": "持仓管理",
    "/stock/dashboard": "仪表盘", "/stock/detail": "个股详情", "/stock/watchlist": "自选股", "/stock/movers": "关注池",
    "/football/dashboard": "赛前模拟", "/football/matches": "比赛列表", "/football/predict": "赛事预测"
  };

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function crumbsHtml() {
    var p = location.pathname || "/";
    if (p.length > 1 && p.charAt(p.length - 1) === "/") { p = p.slice(0, -1); }
    var items = [{ label: "首页", href: "/" }];
    var hub = "";
    for (var k in CRUMB_HUB) {
      if (Object.prototype.hasOwnProperty.call(CRUMB_HUB, k) && (p === k || p.indexOf(k + "/") === 0)) { hub = k; }
    }
    var name = "";
    if (hub) {
      if (p !== hub) { items.push({ label: CRUMB_HUB[hub], href: hub }); }
      name = (p === hub) ? CRUMB_HUB[hub] : (CRUMB_NAME[p] || "");
    } else if (CRUMB_SYS[p]) {
      items.push({ label: "系统", href: "/control-center" });
      name = CRUMB_NAME[p] || "";
    } else {
      name = CRUMB_NAME[p] || "";
    }
    if (!name) {
      name = (document.title || "").replace(/\s*[·\-–].*$/, "").trim() || "当前页";
    }
    var h = '<nav class="ts-crumbs" aria-label="面包屑导航"><ol>';
    for (var i = 0; i < items.length; i++) {
      h += '<li class="ts-crumb-prev"><a href="' + items[i].href + '">' + esc(items[i].label) +
           '</a><span class="ts-sep" aria-hidden="true">/</span></li>';
    }
    h += '<li><span class="ts-crumb-cur" aria-current="page">' + esc(name) + '</span></li></ol></nav>';
    return h;
  }

  var bar = document.createElement("div");
  bar.className = "ts-topnav" + (mode === "float" ? " float" : "");

  var cur = (document.title || "").replace(/\s*[·\-].*$/, "").trim() || "金水谣";
  var healthHtml =
    '<span id="ts-health-dot" class="ts-hdot" style="background:rgba(11,26,47,.4)" title="检测中…"></span>';

  /* ====== 四大子系统快捷入口 ====== */
  var SUB_MENUS = [
    { name: "彩票", href: "/lottery" },
    { name: "基金", href: "/fund" },
    { name: "股票", href: "/stock" },
    { name: "足彩", href: "/football" }
  ];
  function subActive() {
    var p = location.pathname || "";
    for (var i = 0; i < SUB_MENUS.length; i++) {
      if (p === SUB_MENUS[i].href || p.indexOf(SUB_MENUS[i].href + "/") === 0) return SUB_MENUS[i].name;
    }
    return "";
  }
  function subsHtml() {
    var curSub = subActive();
    var h = "";
    for (var i = 0; i < SUB_MENUS.length; i++) {
      var m = SUB_MENUS[i];
      var cls = "ts-sub" + (m.name === curSub ? " on" : "");
      h += '<a class="' + cls + '" href="' + m.href + '">' + m.name + '</a>';
    }
    return h;
  }

  if (mode === "float") {
    bar.innerHTML =
      healthHtml +
      '<a class="ts-brand" href="' + HOME + '">🏠 工作台</a>' +
      '<span class="ts-drop"><button type="button" class="ts-drop-btn">子系统 ▾</button>' +
      '<span class="ts-drop-menu">' + subsHtml() + '</span></span>' +
      '<button type="button" class="ts-theme-btn" id="tsThemeBtn">七色</button>' +
      '<a href="' + PORTAL + '">← 门户</a>';
  } else {
    bar.innerHTML =
      '<a class="ts-brand" href="' + HOME + '">' + healthHtml + '金水谣工作台</a>' +
      crumbsHtml() +
      '<span class="ts-subs">' + subsHtml() + '</span>' +
      '<span class="ts-spacer"></span>' +
      '<a href="/ai-agent">💬 AI助手</a>' +
      '<button type="button" class="ts-theme-btn" id="tsThemeBtn" style="margin-left:2px">七色</button>' +
      '<span class="ts-drop"><button type="button" class="ts-drop-btn">更多 ▾</button>' +
      '<span class="ts-drop-menu">' +
      /* P0-3：原为 /scheduler.html、/engine-dashboard.html，不在路由表里，
         靠 _serve_static 兜底才勉强能开；compare-tech 原写了完整物理路径。
         统一改为已注册路由，避免路由表一改就断链。 */
      '<a href="/ai-agent#knowledge">📚 知识库</a>' +
      '<a href="/sync">📋 看板</a>' +
      '<a href="/scheduler">⏰ 定时任务</a>' +
      '<a href="/engine-dashboard">📊 效果看板</a>' +
      '<a href="/compare-tech">🔬 方案对比</a>' +
      '</span></span>' +
      '<a class="ts-pill" href="' + PORTAL + '">← 返回门户</a>';
  }
  document.body.insertBefore(bar, document.body.firstChild);

  /* 主题按钮：建好 DOM 后再同步一次文案（首屏 applyTheme 时按钮还不存在） */
  var themeBtn = document.getElementById("tsThemeBtn");
  if (themeBtn) {
    applyTheme(readTheme());
    themeBtn.addEventListener("click", function () { applyTheme(nextTheme()); });
  }

  /* 下拉菜单：点击按钮切换，点击外部关闭 */
  function bindDrop() {
    var btns = bar.querySelectorAll(".ts-drop-btn");
    for (var i = 0; i < btns.length; i++) {
      (function (btn) {
        btn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          var m = btn.parentNode.querySelector(".ts-drop-menu");
          var open = m.style.display === "block";
          closeAllDrop();
          m.style.display = open ? "none" : "block";
        });
      })(btns[i]);
    }
    document.addEventListener("click", closeAllDrop);
    function closeAllDrop() {
      var ms = bar.querySelectorAll(".ts-drop-menu");
      for (var j = 0; j < ms.length; j++) ms[j].style.display = "none";
    }
  }
  bindDrop();

  /* 启动健康检查：立即一次 + 每30秒轮询 */
  pollHealth();
  setInterval(pollHealth, 30000);
})();

/* Ctrl+K 全局页面搜索（懒加载 quick-search.js，避免阻塞首屏） */
(function () {
  var loaded = false;
  function load() {
    if (loaded) return;
    loaded = true;
    var s = document.createElement("script");
    s.src = "/Jinshuiyao_Fixed/jinshuiyao-guide/_shared/js/quick-search.js";
    s.async = true;
    document.head.appendChild(s);
  }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && e.key.toLowerCase() === "k") load();
  });
  if (document.readyState === "complete" || document.readyState === "interactive") {
    load();
  } else {
    document.addEventListener("DOMContentLoaded", load);
  }
})();

/* 顶部加载进度条：页面资源加载完成前显示细进度条，load 后淡出 */
(function () {
  var pb = document.createElement("div");
  pb.id = "jsy-progress-bar";
  pb.style.cssText = "position:fixed;top:0;left:0;height:2px;width:20%;background:#C9A96E;z-index:100000;transition:width .5s ease,opacity .4s ease;opacity:0.9;";
  document.body.appendChild(pb);
  if (document.readyState === "complete") {
    pb.style.width = "100%";
    setTimeout(function () { pb.style.opacity = "0"; }, 300);
  } else {
    requestAnimationFrame(function () { pb.style.width = "80%"; });
    window.addEventListener("load", function () {
      pb.style.width = "100%";
      setTimeout(function () { pb.style.opacity = "0"; }, 350);
    });
  }
})();
