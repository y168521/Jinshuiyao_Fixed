/* 共享图表工具：echarts 一键保存 PNG。
   用法：window.saveChartImage(chart, '文件名') —— chart 为 echarts 实例
   页面引用本文件后即可使用；也可通过 bindChartExport(chartEl, chart, name) 自动在容器右上角加存图按钮。 */
(function () {
  if (window.__jsyChartExportLoaded) return;
  window.__jsyChartExportLoaded = true;

  window.saveChartImage = function (chart, filename) {
    if (!chart || !chart.getDataURL) { showToast && showToast('图表未初始化', 'error'); return; }
    try {
      var url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
      var a = document.createElement('a');
      a.href = url;
      a.download = filename || 'chart_' + new Date().toISOString().slice(0, 10) + '.png';
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { a.remove(); }, 300);
      if (window.showToast) showToast('图表已保存 PNG', 'success');
    } catch (e) {
      if (window.showToast) showToast('保存失败：' + e.message, 'error');
    }
  };

  window.bindChartExport = function (chartEl, chart, filename) {
    if (!chartEl || !chart) return;
    var wrap = document.createElement('div');
    wrap.style.cssText = 'position:absolute;top:6px;right:6px;z-index:5;';
    var btn = document.createElement('button');
    btn.textContent = '⤓ 存图';
    btn.style.cssText = 'padding:2px 9px;font-size:11px;border:1px solid rgba(201,169,110,.45);background:rgba(11,26,47,.85);color:#C9A96E;border-radius:5px;cursor:pointer;';
    btn.title = '保存图表为 PNG 图片';
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      window.saveChartImage(chart, filename);
    });
    wrap.appendChild(btn);
    var full = document.createElement('button');
    full.textContent = '⛶ 全屏';
    full.style.cssText = 'padding:2px 9px;font-size:11px;border:1px solid rgba(201,169,110,.45);background:rgba(11,26,47,.85);color:#C9A96E;border-radius:5px;cursor:pointer;margin-left:4px;';
    full.title = '图表全屏查看（Esc 退出）';
    full.addEventListener('click', function (e) {
      e.stopPropagation();
      window.fullscreenChart(chartEl, chart);
    });
    wrap.appendChild(full);
    chartEl.style.position = chartEl.style.position || 'relative';
    chartEl.appendChild(wrap);
  };

  window.fullscreenChart = function (chartEl, chart) {
    if (!chartEl) return;
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;background:#0A1526;display:flex;align-items:center;justify-content:center;';
    var box = document.createElement('div');
    box.style.cssText = 'width:92vw;height:88vh;position:relative;';
    var close = document.createElement('button');
    close.textContent = '✕ 退出 (Esc)';
    close.style.cssText = 'position:absolute;top:-34px;right:0;padding:4px 14px;font-size:12px;border:1px solid rgba(201,169,110,.45);background:rgba(11,26,47,.9);color:#C9A96E;border-radius:5px;cursor:pointer;z-index:10;';
    close.addEventListener('click', exit);
    box.appendChild(close);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    var bigEl = chartEl.cloneNode(true);
    bigEl.style.cssText = 'width:100%;height:100%;position:absolute;top:0;left:0;';
    box.appendChild(bigEl);
    var bigChart = null;
    try {
      if (chart && chart.cloneModel) {
        var newChart = window.echarts.init(bigEl, chart.getOption && chart.getOption().backgroundColor ? undefined : 'dark');
        if (chart.getOption) newChart.setOption(JSON.parse(JSON.stringify(chart.getOption())));
        bigChart = newChart;
      } else {
        bigEl.innerHTML = chartEl.innerHTML;
      }
    } catch (err) {
      bigEl.innerHTML = chartEl.innerHTML;
    }
    function exit() {
      if (bigChart && bigChart.dispose) bigChart.dispose();
      overlay.remove();
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) {
      if (e.key === 'Escape') exit();
    }
    document.addEventListener('keydown', onKey);
  };
})();