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
    chartEl.style.position = chartEl.style.position || 'relative';
    chartEl.appendChild(wrap);
  };
})();