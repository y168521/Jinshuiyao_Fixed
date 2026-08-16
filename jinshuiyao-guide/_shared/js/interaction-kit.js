/* 金水谣 微交互公共组件（W63补98 / JS-20260816-03）
 *  - debounce(fn, ms): 防抖，搜索/刷新类高频触发用
 *  - bindSubmitGuard(btn, fn): 提交防重复——点击即禁用+loading 文案，完成后恢复
 *  - initBackToTop(): 回到顶部按钮（滚动超过 400px 出现）
 * 全 ES5 风格，兼容所有页面。
 */
(function (w) {
  'use strict';
  function debounce(fn, ms) {
    var t = null;
    return function () {
      var self = this, args = arguments;
      if (t) { clearTimeout(t); }
      t = setTimeout(function () { t = null; fn.apply(self, args); }, ms || 300);
    };
  }
  function bindSubmitGuard(btn, fn) {
    if (!btn) { return; }
    var oldText = btn.textContent;
    btn.addEventListener('click', function () {
      if (btn.disabled) { return; }
      btn.disabled = true;
      btn.textContent = oldText.indexOf('…') >= 0 ? oldText : oldText + '…';
      var done = function () {
        btn.disabled = false;
        btn.textContent = oldText;
      };
      try { var r = fn.call(btn); if (r && r.then) { r.then(done, done); } else { done(); } }
      catch (e) { done(); }
    });
  }
  function initBackToTop() {
    var btn = document.createElement('div');
    btn.id = 'jsy-backtop';
    btn.textContent = '↑';
    btn.style.cssText = 'position:fixed;right:18px;bottom:24px;width:38px;height:38px;border-radius:50%;'
      + 'background:rgba(201,169,110,.85);color:#0B1A2F;font-size:17px;font-weight:700;'
      + 'display:none;align-items:center;justify-content:center;cursor:pointer;z-index:999;'
      + 'box-shadow:0 2px 10px rgba(0,0,0,.35);transition:opacity .2s;';
    btn.onclick = function () { w.scrollTo({ top: 0, behavior: 'smooth' }); };
    document.body.appendChild(btn);
    var onScroll = function () {
      btn.style.display = (document.documentElement.scrollTop || document.body.scrollTop) > 400
        ? 'flex' : 'none';
    };
    w.addEventListener('scroll', debounce(onScroll, 120), { passive: true });
    onScroll();
  }
  w.InteractionKit = { debounce: debounce, bindSubmitGuard: bindSubmitGuard, initBackToTop: initBackToTop };
})(window);