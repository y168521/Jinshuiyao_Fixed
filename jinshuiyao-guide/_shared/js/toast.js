/* 共享 Toast 组件（七色体系统一风格）
 * 用法: showToast('保存成功', 'success'|'error'|'warn'|'info')
 * 兼容旧调用: showToast('提示') 默认 info
 * 全站页面统一由此文件提供，页面内禁止再定义本地 showToast */
(function () {
  if (window.__jsyToastLoaded) return;
  window.__jsyToastLoaded = true;

  window.showToast = function (message, type) {
    type = type || 'info';
    var colors = { success: '#2D8B7E', error: '#C8755A', warn: '#C9A96E', info: '#3A5A80' };
    var toast = document.createElement('div');
    toast.textContent = message;
    toast.style.cssText =
      'position:fixed;bottom:24px;right:24px;padding:10px 20px;border-radius:8px;font-size:13px;' +
      'z-index:99999;background:' + (colors[type] || colors.info) + ';color:#fff;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.45);transition:opacity .4s;opacity:1;' +
      'max-width:440px;word-break:break-all;pointer-events:none;';
    document.body.appendChild(toast);
    setTimeout(function () {
      toast.style.opacity = '0';
      setTimeout(function () { toast.remove(); }, 400);
    }, 3000);
  };
})();