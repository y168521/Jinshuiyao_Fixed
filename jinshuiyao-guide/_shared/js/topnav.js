/* 金水谣统一顶栏：被所有子页面引用，提供"随时返回工作台 / 门户"的导航。
   两种模式：
   - 默认（bar）：通栏吸顶，适合普通文档页；
   - data-nav="float"（写在 <body> 上）：右上角悬浮胶囊，适合全屏对话类应用（如 AI助手），不破坏布局。
   新增：健康状态指示器（绿/黄/红点）+ 自动重试安全请求工具 safeFetch()。
   纯原生 JS，无任何依赖。 */
(function () {
  "use strict";
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

  if (mode === "float") {
    bar.innerHTML =
      healthHtml +
      '<a class="ts-brand" href="' + HOME + '">🏠 工作台</a>' +
      '<a href="' + PORTAL + '">← 门户</a>';
  } else {
    bar.innerHTML =
      '<a class="ts-brand" href="' + HOME + '">' + healthHtml + '金水谣工作台</a>' +
      '<span class="ts-cur">' + cur + '</span>' +
      '<span class="ts-spacer"></span>' +
      '<a href="/ai-agent">💬 AI助手</a>' +
      '<a href="/ai-agent#knowledge">📚 知识库</a>' +
      '<a href="/sync">📋 看板</a>' +
      '<a href="/scheduler.html">⏰ 定时任务</a>' +
      '<a href="/engine-dashboard.html">📊 效果看板</a>' +
      '<a href="/Jinshuiyao_Fixed/jinshuiyao-guide/compare-tech.html">🔬 方案对比</a>' +
      '<a class="ts-pill" href="' + PORTAL + '">← 返回门户</a>';
  }
  document.body.insertBefore(bar, document.body.firstChild);

  /* 启动健康检查：立即一次 + 每30秒轮询 */
  pollHealth();
  setInterval(pollHealth, 30000);
})();
