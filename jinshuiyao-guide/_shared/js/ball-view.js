/* 金水谣 号码彩色球组件（W63补99 / JS-20260816-04）
 *  - BallView.balls(numsStr, lot): 号码串 → 彩色球 HTML（双色球/大乐透按前后区配色，其余金色）
 *  - BallView.injectStyles(): 注入公共球样式（幂等）
 * 全 ES5，无依赖。
 */
(function (w) {
  'use strict';
  var _injected = false;
  var STYLE = '.jsy-ball{display:inline-flex;align-items:center;justify-content:center;'
    + 'width:26px;height:26px;border-radius:50%;font-size:12px;font-weight:700;'
    + 'margin:1px 2px;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.4);'
    + 'border:1px solid rgba(255,255,255,.25);font-variant-numeric:tabular-nums;}'
    + '.jsy-ball-red{background:linear-gradient(135deg,#D9867A,#C0584A);}'
    + '.jsy-ball-blue{background:linear-gradient(135deg,#5A8FD9,#2F5FA8);}'
    + '.jsy-ball-gold{background:linear-gradient(135deg,#DDBE7C,#B08A3E);}'
    + '.jsy-ball-teal{background:linear-gradient(135deg,#4FA89A,#2D7A6E);}'
    + '.jsy-ball-sm{width:21px;height:21px;font-size:11px;}';
  function injectStyles() {
    if (_injected) { return; }
    _injected = true;
    var st = document.createElement('style');
    st.textContent = STYLE;
    document.head.appendChild(st);
  }
  function ball(n, cls, small) {
    return '<span class="jsy-ball ' + cls + (small ? ' jsy-ball-sm' : '') + '">'
      + String(n).padStart(2, '0') + '</span>';
  }
  function balls(numsStr, lot, small) {
    if (!numsStr) { return ''; }
    var parts = String(numsStr).split('+');
    var reds = parts[0] ? parts[0].trim().split(/[\s,]+/).filter(Boolean) : [];
    var blues = parts[1] ? parts[1].trim().split(/[\s,]+/).filter(Boolean) : [];
    var lotCn = lot || '';
    var redCls = (lotCn.indexOf('双色球') >= 0 || lotCn.indexOf('大乐透') >= 0) ? 'jsy-ball-red' : 'jsy-ball-gold';
    var blueCls = lotCn.indexOf('双色球') >= 0 ? 'jsy-ball-blue' : 'jsy-ball-gold';
    var html = '';
    for (var i = 0; i < reds.length; i++) { html += ball(reds[i], redCls, small); }
    for (var j = 0; j < blues.length; j++) { html += ball(blues[j], blueCls, small); }
    return html;
  }
  w.BallView = { balls: balls, injectStyles: injectStyles };
})(window);