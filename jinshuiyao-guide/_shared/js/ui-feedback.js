/* 共享反馈组件：Toast / Confirm / Modal
 * 七色体系统一风格（令牌驱动），无障碍（role=dialog / aria-modal / ESC 取消 / 焦点陷阱 / 锁滚动）
 * 自包含：若已加载 toast.js 的 showToast 则复用，否则自带兜底；页面只需引入本文件即可获得 toast+confirm+modal。
 * 用法：
 *   JSY.toast('保存成功', 'success'|'error'|'warn'|'info')
 *   JSY.confirm('确定删除？', {title, okText, cancelText}).then(function(ok){ if(ok) ... })
 *   JSY.modal({ title, bodyText, actions:[{key,label,primary}], cancelKey }).then(function(key){ ... })
 */
(function () {
  if (window.__jsyFeedbackLoaded) return;
  window.__jsyFeedbackLoaded = true;

  /* ── Toast（复用 toast.js 或自带兜底）── */
  if (!window.showToast) {
    window.showToast = function (message, type) {
      type = type || 'info';
      var palette = { success: '#2D8B7E', error: '#C8755A', warn: '#C9A96E', info: '#5BC0DE' };
      var toast = document.createElement('div');
      toast.setAttribute('role', 'status');
      toast.textContent = message;
      toast.style.cssText =
        'position:fixed;bottom:24px;right:24px;padding:10px 20px;border-radius:8px;font-size:13px;' +
        'z-index:99999;background:' + (palette[type] || palette.info) + ';color:#fff;' +
        'box-shadow:0 4px 14px rgba(0,0,0,.45);transition:opacity .4s;opacity:1;' +
        'max-width:440px;word-break:break-all;pointer-events:none;';
      document.body.appendChild(toast);
      setTimeout(function () {
        toast.style.opacity = '0';
        setTimeout(function () { toast.remove(); }, 400);
      }, 3000);
    };
  }
  var JSY = window.JSY || (window.JSY = {});
  JSY.toast = function (msg, type) { window.showToast(msg, type); };

  /* ── 通用对话框底座 ── */
  function openDialog(opts) {
    var backdrop = document.createElement('div');
    backdrop.className = 'jsy-fb-backdrop';

    var dialog = document.createElement('div');
    dialog.className = 'jsy-fb-dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    if (opts.title) dialog.setAttribute('aria-label', opts.title);

    if (opts.title) {
      var h = document.createElement('div');
      h.className = 'jsy-fb-title';
      h.textContent = opts.title;
      dialog.appendChild(h);
    }
    var body = document.createElement('div');
    body.className = 'jsy-fb-body';
    if (opts.bodyNode) body.appendChild(opts.bodyNode);
    else body.textContent = opts.bodyText || '';
    dialog.appendChild(body);

    var footer = document.createElement('div');
    footer.className = 'jsy-fb-actions';
    (opts.actions || []).forEach(function (a) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn jsy-fb-btn' + (a.primary ? ' jsy-fb-btn--primary' : '');
      b.textContent = a.label;
      b.addEventListener('click', function () { close(a.key); });
      footer.appendChild(b);
    });
    dialog.appendChild(footer);

    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);
    var prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function focusables() {
      return dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    }
    var f = focusables();
    if (f.length) f[0].focus();

    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(opts.cancelKey != null ? opts.cancelKey : (opts.actions[opts.actions.length - 1] || {}).key);
        return;
      }
      if (e.key === 'Tab') {
        var list = focusables();
        if (!list.length) return;
        var first = list[0], last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('mousedown', function (e) {
      if (e.target === backdrop) close(opts.cancelKey != null ? opts.cancelKey : (opts.actions[opts.actions.length - 1] || {}).key);
    });

    function close(key) {
      document.removeEventListener('keydown', onKey);
      backdrop.remove();
      document.body.style.overflow = prevOverflow;
      if (opts.onClose) opts.onClose(key);
    }
    return { close: close };
  }

  /* ── Confirm：返回 Promise<boolean> ── */
  JSY.confirm = function (message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      openDialog({
        title: opts.title || '请确认',
        bodyText: message,
        actions: [
          { key: 'ok', label: opts.okText || '确定', primary: true },
          { key: 'cancel', label: opts.cancelText || '取消', primary: false }
        ],
        cancelKey: 'cancel',
        onClose: function (key) { resolve(key === 'ok'); }
      });
    });
  };

  /* ── Modal：返回 Promise<actionKey> ── */
  JSY.modal = function (opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      openDialog({
        title: opts.title,
        bodyNode: opts.bodyNode,
        bodyText: opts.bodyText,
        actions: opts.actions || [{ key: 'close', label: '关闭', primary: true }],
        cancelKey: opts.cancelKey,
        onClose: function (key) { resolve(key); }
      });
    });
  };
})();
