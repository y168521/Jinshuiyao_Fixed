(function() {
  var data = window.TREND_DATA;
  if (!data) { document.getElementById('panels').innerHTML = '<p style="padding:2rem;color:#7a8499">暂无走势数据，请先运行预测系统生成数据</p>'; return; }

  var ACCENT = '#00d4aa', DANGER = '#ff6b6b', GOLD = '#ffd93d', BLUE = '#60a5fa', PURPLE = '#b197fc';
  var MUTED = '#7a8499', BORDER = '#1e2a40', CARD = '#131a2a', TEXT = '#e4e8f1';

  var now = new Date();
  document.getElementById('updateTime').textContent = '更新: ' + now.getFullYear() + '-' +
    String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0') + ' ' +
    String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0');

  var tabsEl = document.getElementById('tabs');
  var panelsEl = document.getElementById('panels');
  var allCharts = {}; // cache: name -> [chart instances]

  var lotNames = Object.keys(data).sort(function(a,b) { return a.localeCompare(b); });
  var priority = ['福彩3D','排列三','双色球','大乐透','七乐彩','七星彩','快乐8'];
  lotNames.sort(function(a,b) { return priority.indexOf(a) - priority.indexOf(b); });

  lotNames.forEach(function(name, idx) {
    var tab = document.createElement('div');
    tab.className = 'tab' + (idx === 0 ? ' active' : '');
    tab.textContent = name;
    tab.setAttribute('data-idx', idx);
    tab.onclick = function() {
      var clickedIdx = parseInt(this.getAttribute('data-idx'));
      document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
      document.querySelectorAll('.panel').forEach(function(p) { p.classList.remove('active'); });
      this.classList.add('active');
      document.getElementById('panel-' + clickedIdx).classList.add('active');
      // VFix: resize charts for the now-visible panel
      setTimeout(function() { resizeCharts(lotNames[clickedIdx]); }, 100);
    };
    tabsEl.appendChild(tab);

    var panel = document.createElement('div');
    panel.className = 'panel' + (idx === 0 ? ' active' : '');
    panel.id = 'panel-' + idx;
    panel.innerHTML = buildPanelHTML(name, data[name]);
    panelsEl.appendChild(panel);
  });

  // Init all charts (even hidden ones - ECharts SVG handles this)
  lotNames.forEach(function(name) {
    allCharts[name] = [];
  });
  lotNames.forEach(function(name) {
    initLotteryCharts(name, data[name]);
  });

  // Global resize
  window.addEventListener('resize', function() {
    lotNames.forEach(function(name) { resizeCharts(name); });
  });

  function resizeCharts(name) {
    if (allCharts[name]) {
      allCharts[name].forEach(function(c) {
        try { c.resize(); } catch(e) {}
      });
    }
  }

  function buildPanelHTML(name, d) {
    var isDigit = name === '福彩3D' || name === '排列三';
    var html = '';
    if (isDigit && d.digit_trend) {
      html += '<div class="grid-2">';
      html += mkCard('按位走势图（百位/十位/个位）', 'chart-digit-' + name, 'chart-box-tall', ACCENT);
      html += mkCard('号码频率热力图', 'chart-heat-' + name, 'chart-box', DANGER);
      html += '</div>';
      html += '<div class="grid-2">';
      html += mkCard('遗漏值走势（最近30期）', 'chart-miss-' + name, 'chart-box-tall', BLUE);
      html += mkCard('冷热号趋势', 'chart-hc-' + name, 'chart-box', GOLD);
      html += '</div>';
    } else {
      html += '<div class="grid-2">';
      html += mkCard('号码走势（最近50期）', 'chart-red-' + name, 'chart-box-tall', ACCENT);
      html += mkCard('三区分布趋势', 'chart-zone-' + name, 'chart-box', PURPLE);
      html += '</div>';
      html += mkCard('遗漏值走势（最近30期）', 'chart-miss-' + name, 'chart-box-tall', BLUE);
    }
    return html;
  }

  function mkCard(title, id, cls, dotColor) {
    return '<div class="chart-card"><div class="title"><span class="dot" style="background:' + dotColor + '"></span>' + title + '</div><div id="' + id + '" class="' + (cls||'chart-box') + '"></div></div>';
  }

  function initChart(name, id, option) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      var c = echarts.init(el, 'jinshuiyao', { renderer: 'svg' });
      c.setOption(option);
      allCharts[name].push(c);
      return c;
    } catch(e) {
      console.warn('Chart init failed for ' + id + ':', e);
      return null;
    }
  }

  function initLotteryCharts(name, d) {
    var isDigit = name === '福彩3D' || name === '排列三';
    var tp = { trigger: 'axis', appendToBody: true, backgroundColor: CARD, borderColor: BORDER, textStyle: { color: TEXT, fontSize: 12 } };
    function xAx(dat) { return { data: dat, axisLine: { lineStyle: { color: BORDER } }, axisLabel: { color: MUTED, fontSize: 10, rotate: dat.length > 15 ? 45 : 0 }, splitLine: { lineStyle: { color: BORDER, type: 'dashed' } } }; }
    function yAx() { return { axisLine: { lineStyle: { color: BORDER } }, axisLabel: { color: MUTED }, splitLine: { lineStyle: { color: BORDER, type: 'dashed' } } }; }

    if (isDigit && d.digit_trend) {
      var periods = d.digit_trend['百位'].map(function(x) { return String(x.period); });
      var pos = ['百位','十位','个位'];
      var posColors = [ACCENT, GOLD, BLUE];
      var srs = pos.map(function(p, pi) {
        return { name: p, type: 'line', data: d.digit_trend[p].map(function(x) { return x.num; }),
          symbol: 'circle', symbolSize: 6, lineStyle: { color: posColors[pi], width: 2 }, itemStyle: { color: posColors[pi] } };
      });
      initChart(name, 'chart-digit-' + name, { animation: false, tooltip: tp,
        legend: { data: pos, textStyle: { color: MUTED }, bottom: 0 },
        grid: { top: 30, bottom: 40, left: 50, right: 20 },
        xAxis: Object.assign({}, xAx(periods), { type: 'category' }),
        yAxis: Object.assign({}, yAx(), { type: 'value', min: 0, max: 9, splitNumber: 9 }),
        series: srs });

      // Heatmap
      var heatData = [];
      for (var r = 0; r < d.frequency_heatmap.length; r++)
        for (var c = 0; c < d.frequency_heatmap[r].length; c++)
          heatData.push([c, r, d.frequency_heatmap[r][c]]);
      initChart(name, 'chart-heat-' + name, { animation: false,
        tooltip: { appendToBody: true, formatter: function(p) { return p.data[1]+'位 号码'+p.data[0]+': '+p.data[2]+'次'; } },
        grid: { top: 10, bottom: 30, left: 60, right: 60 },
        xAxis: { type: 'category', data: Array.from({length:10},function(_,i){return i;}), name:'号码', axisLine:{lineStyle:{color:BORDER}}, axisLabel:{color:MUTED}, nameTextStyle:{color:MUTED} },
        yAxis: { type: 'category', data: pos, axisLine:{lineStyle:{color:BORDER}}, axisLabel:{color:MUTED} },
        visualMap: { min: 0, max: 15, calculable: true, orient: 'horizontal', right: 10, top: 'center', inRange: { color: ['#131a2a','#1a5c4a','#00d4aa'] }, textStyle: { color: MUTED } },
        series: [{ type: 'heatmap', data: heatData, label: { show: true, color: TEXT, fontSize: 11 } }] });

      // Miss
      if (d.miss_chart) buildMissChart(name, d, tp, xAx, yAx);

      // Hot/cold
      if (d.hot_cold_trend) {
        var hcS = 30, hcSt = d.hot_cold_trend.dates.length - hcS;
        initChart(name, 'chart-hc-' + name, { animation: false, tooltip: tp,
          legend: { data: ['热号','温号','冷号'], textStyle: { color: MUTED }, bottom: 0 },
          grid: { top: 30, bottom: 40, left: 50, right: 20 },
          xAxis: Object.assign({}, xAx(d.hot_cold_trend.dates.slice(hcSt)), { type: 'category' }),
          yAxis: Object.assign({}, yAx(), { type: 'value', max: 10, name: '号码数', nameTextStyle: { color: MUTED } }),
          series: [
            { name:'热号', type:'bar', stack:'h', data:d.hot_cold_trend.hot.slice(hcSt), itemStyle:{color:DANGER} },
            { name:'温号', type:'bar', stack:'h', data:d.hot_cold_trend.warm.slice(hcSt), itemStyle:{color:GOLD} },
            { name:'冷号', type:'bar', stack:'h', data:d.hot_cold_trend.cold.slice(hcSt), itemStyle:{color:BLUE} }
          ] });
      }
    } else {
      // Non-digit: scatter + zone + miss
      if (d.red_trend) {
        var scatterData = [];
        d.red_trend.forEach(function(item) { item.nums.forEach(function(num) { scatterData.push([String(item.period), num]); }); });
        var allP = d.red_trend.map(function(x) { return String(x.period); });
        var rmin=999,rmax=0; scatterData.forEach(function(dd) { rmin=Math.min(rmin,dd[1]); rmax=Math.max(rmax,dd[1]); });
        initChart(name, 'chart-red-' + name, { animation: false,
          tooltip: { appendToBody: true, formatter: function(p) { return '第'+p.data[0]+'期: '+p.data[1]; } },
          grid: { top: 30, bottom: 40, left: 50, right: 20 },
          xAxis: Object.assign({}, xAx(allP.slice(-30)), { type: 'category' }),
          yAxis: Object.assign({}, yAx(), { type: 'value', min: rmin-1, max: rmax+1, name: '号码', nameTextStyle: { color: MUTED } }),
          series: [{ type: 'scatter', data: scatterData.slice(-200), symbolSize: 6, itemStyle: { color: ACCENT } }] });
      }

      if (d.zone_distribution) {
        var zN = 30, zSt = d.zone_distribution.dates.length - zN;
        initChart(name, 'chart-zone-' + name, { animation: false, tooltip: tp,
          legend: { data: ['一区','二区','三区'], textStyle: { color: MUTED }, bottom: 0 },
          grid: { top: 30, bottom: 40, left: 50, right: 20 },
          xAxis: Object.assign({}, xAx(d.zone_distribution.dates.slice(zSt)), { type: 'category' }),
          yAxis: Object.assign({}, yAx(), { type: 'value', name: '个数', nameTextStyle: { color: MUTED } }),
          series: [
            { name:'一区', type:'bar', stack:'z', data:d.zone_distribution.zone1.slice(zSt), itemStyle:{color:ACCENT} },
            { name:'二区', type:'bar', stack:'z', data:d.zone_distribution.zone2.slice(zSt), itemStyle:{color:GOLD} },
            { name:'三区', type:'bar', stack:'z', data:d.zone_distribution.zone3.slice(zSt), itemStyle:{color:BLUE} }
          ] });
      }

      if (d.miss_chart) buildMissChart(name, d, tp, xAx, yAx);
    }
  }

  function buildMissChart(name, d, tp, xAx, yAx) {
    if (!d.miss_chart || !d.miss_chart.series) return;
    var maxSeries = name === '福彩3D' || name === '排列三' ? d.miss_chart.series.length : Math.min(d.miss_chart.series.length, 20);
    var mSeries = d.miss_chart.series.slice(0, maxSeries).map(function(s) {
      return { name: s.name, type: 'line', data: s.data, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: MUTED } };
    });
    // Highlight top 3
    var sorted = d.miss_chart.series.slice(0, maxSeries).sort(function(a,b) { return (b.data[b.data.length-1]||0) - (a.data[a.data.length-1]||0); });
    var topNames = sorted.slice(0, 3).map(function(s) { return s.name; });
    var hiColors = [DANGER, GOLD, BLUE];
    mSeries.forEach(function(ms) {
      var hi = topNames.indexOf(ms.name);
      if (hi >= 0) ms.lineStyle = { width: 2.5, color: hiColors[hi] };
    });
    initChart(name, 'chart-miss-' + name, { animation: false, tooltip: tp,
      legend: { type: 'scroll', bottom: 0, textStyle: { color: MUTED, fontSize: 10 }, pageTextStyle: { color: MUTED } },
      grid: { top: 30, bottom: 50, left: 50, right: 20 },
      xAxis: Object.assign({}, xAx(d.miss_chart.dates.slice(-20)), { type: 'category' }),
      yAxis: Object.assign({}, yAx(), { type: 'value', name: '遗漏期数', nameTextStyle: { color: MUTED } }),
      series: mSeries });
  }
})();
