/* 金水谣前端错误监控脚本
 * 用途：自动捕获页面中的 JS 运行时错误和未处理的 Promise 拒绝，
 *       通过 navigator.sendBeacon 上报到后端 /api/error-report 接口，
 *       写入 金水谣数据/log/err_log/frontend_errors.jsonl 供排查问题。
 * 特性：
 *   - 捕获 window.onerror（同步错误）
 *   - 捕获 unhandledrejection（异步 Promise 错误）
 *   - 同一错误 5 秒内不重复上报（节流去重）
 *   - 使用 sendBeacon 确保页面关闭时也能发出请求
 * 引入方式：在 </body> 前加 <script src="_shared/js/error-monitor.js"></script>
 */
(function () {
  "use strict";

  var REPORT_URL = "/api/error-report";
  var THROTTLE_MS = 5000; // 同一错误 5 秒内不重复上报

  // 节流记录：key -> 上次上报时间戳
  var _lastReport = {};

  /**
   * 生成错误的去重 key（message + source + lineno）
   */
  function errorKey(message, source, lineno) {
    return (message || "") + "|" + (source || "") + "|" + (lineno || 0);
  }

  /**
   * 检查是否应该节流（5秒内同一错误不重复上报）
   */
  function shouldThrottle(key) {
    var now = Date.now();
    if (_lastReport[key] && (now - _lastReport[key]) < THROTTLE_MS) {
      return true;
    }
    _lastReport[key] = now;
    return false;
  }

  /**
   * 上报错误到后端
   */
  function reportError(payload) {
    try {
      var key = errorKey(payload.message, payload.source, payload.lineno);
      if (shouldThrottle(key)) {
        return; // 节流：跳过重复上报
      }

      var body = JSON.stringify({
        message: payload.message || "",
        source: payload.source || "",
        lineno: payload.lineno || 0,
        colno: payload.colno || 0,
        stack: payload.stack || "",
        page: location.pathname + location.search,
        ua: navigator.userAgent,
        timestamp: new Date().toISOString()
      });

      // 优先使用 sendBeacon（页面关闭时也能发出）
      if (navigator.sendBeacon) {
        navigator.sendBeacon(REPORT_URL, body);
      } else {
        // 降级：用 fetch 的 keepalive 模式
        fetch(REPORT_URL, {
          method: "POST",
          body: body,
          keepalive: true,
          headers: { "Content-Type": "application/json" }
        }).catch(function () { /* 静默失败 */ });
      }
    } catch (e) {
      // 上报逻辑本身出错时静默忽略，避免死循环
    }
  }

  // ===== 捕获同步 JS 错误 =====
  window.onerror = function (message, source, lineno, colno, error) {
    try {
      reportError({
        message: String(message || "Unknown error"),
        source: source || "",
        lineno: lineno || 0,
        colno: colno || 0,
        stack: (error && error.stack) ? error.stack.substring(0, 2000) : ""
      });
    } catch (e) { /* 静默 */ }
    // 不阻止默认行为（返回 undefined），浏览器控制台仍可见
  };

  // ===== 捕获未处理的 Promise 拒绝 =====
  window.addEventListener("unhandledrejection", function (event) {
    try {
      var reason = event.reason;
      var message = "";
      var stack = "";

      if (reason instanceof Error) {
        message = reason.message || String(reason);
        stack = (reason.stack || "").substring(0, 2000);
      } else if (typeof reason === "string") {
        message = reason;
      } else {
        try {
          message = JSON.stringify(reason);
        } catch (e) {
          message = String(reason);
        }
      }

      reportError({
        message: "[UnhandledRejection] " + message,
        source: "",
        lineno: 0,
        colno: 0,
        stack: stack
      });
    } catch (e) { /* 静默 */ }
  });

})();
