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
      '<circle cx="50" cy="44" r="8" fill="#3B82F6"/>' +
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
    var colors = { ok: "#2D8B7E", degraded: "#C9A96E", error: "#C8755A", unknown: "rgba(11,26,47,.4)" };
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
  var css =
    ".ts-topnav{box-sizing:border-box;display:flex;align-items:center;gap:14px;" +
    "background:#0B1A2F;border-bottom:1px solid rgba(201,169,110,.18);padding:0 18px;height:52px;" +
    "font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC',system-ui,sans-serif;" +
    "z-index:99999;flex-shrink:0;backdrop-filter:blur(8px)}" +
    ".ts-topnav a{text-decoration:none;color:rgba(232,236,241,.7);font-size:14px;font-weight:600;white-space:nowrap;transition:color .2s}" +
    ".ts-topnav a:hover{color:#C9A96E}" +
    ".ts-topnav .ts-brand{color:#C9A96E;font-size:16px;font-weight:800;letter-spacing:.5px;display:flex;align-items:center;gap:8px}" +
    ".ts-topnav .ts-cur{color:#E8ECF1;font-size:14px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    ".ts-topnav .ts-subs{display:flex;align-items:center;gap:6px;margin-left:8px}" +
    ".ts-topnav .ts-sub{font-size:13px;font-weight:600;padding:4px 10px;border-radius:999px;border:1px solid rgba(201,169,110,.18);color:rgba(232,236,241,.75);transition:all .2s}" +
    ".ts-topnav .ts-sub:hover{color:#C9A96E;border-color:rgba(201,169,110,.5)}" +
    ".ts-topnav .ts-sub.on{color:#0B1A2F;background:#C9A96E;border-color:#C9A96E;font-weight:700}" +
    ".ts-topnav .ts-drop{position:relative}" +
    ".ts-topnav .ts-drop-btn{background:transparent;border:1px solid rgba(201,169,110,.25);color:#C9A96E;font-size:13px;font-weight:600;font-family:inherit;padding:4px 10px;border-radius:999px;cursor:pointer;white-space:nowrap}" +
    ".ts-topnav .ts-drop-btn:hover{background:rgba(201,169,110,.12)}" +
    ".ts-topnav .ts-drop-menu{display:none;position:absolute;top:calc(100% + 6px);right:0;min-width:150px;background:rgba(13,31,53,.97);border:1px solid rgba(201,169,110,.25);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.5);padding:6px;z-index:99998}" +
    ".ts-topnav .ts-drop-menu a{display:block;padding:8px 12px;border-radius:6px;font-size:13px;color:rgba(232,236,241,.8)}" +
    ".ts-topnav .ts-drop-menu a:hover{background:rgba(201,169,110,.12);color:#C9A96E}" +
    ".ts-topnav .ts-spacer{flex:1}" +
    ".ts-topnav .ts-pill{background:rgba(201,169,110,.12);color:#C9A96E;padding:6px 12px;border-radius:999px;font-size:13px;border:1px solid rgba(201,169,110,.25)}" +
    ".ts-topnav.float{position:fixed;top:12px;right:12px;left:auto;width:auto;border:none;" +
    "background:rgba(13,31,53,.95);border-radius:999px;box-shadow:0 6px 20px rgba(0,0,0,.4);padding:8px 14px;height:auto;border:1px solid rgba(201,169,110,.18)}" +
    ".ts-topnav.float .ts-cur,.ts-topnav.float .ts-spacer{display:none}" +
    /* 健康指示灯 */
    ".ts-hdot{width:10px;height:10px;border-radius:50%;display:inline-block;flex-shrink:0;" +
    "transition:background-color .3s;box-shadow:0 0 6px rgba(0,0,0,.3)}";

  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

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
      '<a href="' + PORTAL + '">← 门户</a>';
  } else {
    bar.innerHTML =
      '<a class="ts-brand" href="' + HOME + '">' + healthHtml + '金水谣工作台</a>' +
      '<span class="ts-cur">' + cur + '</span>' +
      '<span class="ts-subs">' + subsHtml() + '</span>' +
      '<span class="ts-spacer"></span>' +
      '<a href="/ai-agent">💬 AI助手</a>' +
      '<span class="ts-drop"><button type="button" class="ts-drop-btn">更多 ▾</button>' +
      '<span class="ts-drop-menu">' +
      '<a href="/ai-agent#knowledge">📚 知识库</a>' +
      '<a href="/sync">📋 看板</a>' +
      '<a href="/scheduler.html">⏰ 定时任务</a>' +
      '<a href="/engine-dashboard.html">📊 效果看板</a>' +
      '<a href="/Jinshuiyao_Fixed/jinshuiyao-guide/compare-tech.html">🔬 方案对比</a>' +
      '</span></span>' +
      '<a class="ts-pill" href="' + PORTAL + '">← 返回门户</a>';
  }
  document.body.insertBefore(bar, document.body.firstChild);

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
