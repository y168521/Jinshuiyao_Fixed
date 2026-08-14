/* 共享状态组件：加载中 / 加载失败(带重试) / 空数据。
   用法：
   - StateUI.loading(el, msg)         —— 灰色加载提示（转圈+文字）
   - StateUI.error(el, msg, onRetry)  —— 失败提示（错误原因 + 重试按钮）
   - StateUI.empty(el, msg, hint)     —— 空态（友好文案 + 引导提示）
   纯原生 JS，样式内联，与七色体系一致。 */
(function () {
  if (window.__jsyStateUiLoaded) return;
  window.__jsyStateUiLoaded = true;

  var S = {
    loading: function (el, msg) {
      if (!el) return;
      el.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;gap:10px;padding:28px 12px;color:#8A94A6;font-size:13px;">' +
        '<span style="width:16px;height:16px;border:2px solid rgba(201,169,110,.3);border-top-color:#C9A96E;border-radius:50%;animation:jsy-spin 0.9s linear infinite;"></span>' +
        (msg || '加载中…') + '</div>' +
        '<style>@keyframes jsy-spin{to{transform:rotate(360deg)}}</style>';
    },
    error: function (el, msg, onRetry) {
      if (!el) return;
      var btn = '<button id="jsy-retry-btn" style="margin-left:12px;padding:4px 14px;border:1px solid rgba(201,169,110,.5);background:transparent;color:#C9A96E;border-radius:6px;cursor:pointer;font-size:12px;">重试</button>';
      el.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;flex-wrap:wrap;padding:28px 12px;color:#C8755A;font-size:13px;text-align:center;">' +
        '⚠ ' + (msg || '加载失败') + btn + '</div>';
      var b = el.querySelector('#jsy-retry-btn');
      if (b && onRetry) b.addEventListener('click', onRetry);
    },
    empty: function (el, msg, hint) {
      if (!el) return;
      el.innerHTML =
        '<div style="padding:32px 12px;text-align:center;color:#8A94A6;font-size:13px;">' +
        '<div style="font-size:30px;margin-bottom:8px;">🗂</div>' +
        '<div>' + (msg || '暂无数据') + '</div>' +
        (hint ? '<div style="margin-top:6px;font-size:12px;color:#5B6B81;">' + hint + '</div>' : '') +
        '</div>';
    }
  };
  window.StateUI = S;
})();