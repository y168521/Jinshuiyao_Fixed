(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var accent3 = style.getPropertyValue('--accent3').trim();
  var accent4 = style.getPropertyValue('--accent4').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Radar Chart: 金水谣 vs 竞品 ---
  var radar = echarts.init(document.getElementById('chartRadar'), 'jinshuiyao', { renderer: 'svg' });
  radar.setOption({
    animation: false,
    tooltip: { appendToBody: true },
    legend: {
      data: ['金水谣系统', '福码云数', '开源AI项目'],
      bottom: 10,
      textStyle: { color: muted, fontSize: 12 },
      itemWidth: 16,
      itemHeight: 10
    },
    radar: {
      indicator: [
        { name: '冷热号分析', max: 10 },
        { name: '遗漏分析', max: 10 },
        { name: '杀号引擎', max: 10 },
        { name: '走势可视化', max: 10 },
        { name: '形态约束', max: 10 },
        { name: '深度学习', max: 10 },
        { name: '自适应学习', max: 10 },
        { name: '多方案对比', max: 10 },
        { name: '风险控制', max: 10 },
        { name: '跨期关联', max: 10 }
      ],
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: ink, fontSize: 11 },
      splitLine: { lineStyle: { color: rule } },
      splitArea: { areaStyle: { color: ['transparent', bg2] } },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: [7, 0, 0, 2, 0, 0, 8, 9, 9, 0],
          name: '金水谣系统',
          lineStyle: { color: accent, width: 2 },
          areaStyle: { color: accent + '30' },
          itemStyle: { color: accent },
          symbol: 'circle',
          symbolSize: 5
        },
        {
          value: [8, 9, 8, 9, 8, 7, 4, 3, 2, 6],
          name: '福码云数',
          lineStyle: { color: accent3, width: 2 },
          areaStyle: { color: accent3 + '20' },
          itemStyle: { color: accent3 },
          symbol: 'circle',
          symbolSize: 5
        },
        {
          value: [6, 5, 4, 5, 5, 9, 3, 2, 1, 5],
          name: '开源AI项目',
          lineStyle: { color: accent4, width: 2 },
          areaStyle: { color: accent4 + '20' },
          itemStyle: { color: accent4 },
          symbol: 'circle',
          symbolSize: 5
        }
      ]
    }]
  });
  window.addEventListener('resize', function() { radar.resize(); });

  // --- Bar Chart: 功能缺失对命中率的预期提升贡献 ---
  var impact = echarts.init(document.getElementById('chartImpact'), 'jinshuiyao', { renderer: 'svg' });
  impact.setOption({
    animation: false,
    tooltip: {
      appendToBody: true,
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    grid: {
      left: 100,
      right: 40,
      top: 30,
      bottom: 50
    },
    xAxis: {
      type: 'value',
      name: '预期命中率提升',
      nameTextStyle: { color: muted, fontSize: 11 },
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: muted, formatter: '{value}%' },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } }
    },
    yAxis: {
      type: 'category',
      data: ['五模型Stacking融合', '移动端/Web端', '走势图可视化', '跨期号码关联', '定胆算法升级', '杀号条件引擎', '深度学习LSTM', '形态约束层', '遗漏值分析'],
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: ink, fontSize: 11 },
      axisTick: { show: false }
    },
    series: [
      {
        name: '预期提升',
        type: 'bar',
        data: [
          { value: 8, itemStyle: { color: accent4 + '99' } },
          { value: 1, itemStyle: { color: accent4 + '60' } },
          { value: 3, itemStyle: { color: accent3 } },
          { value: 5, itemStyle: { color: accent3 } },
          { value: 4, itemStyle: { color: accent3 } },
          { value: 7, itemStyle: { color: accent2 } },
          { value: 6, itemStyle: { color: accent2 } },
          { value: 6, itemStyle: { color: accent2 } },
          { value: 8, itemStyle: { color: accent2 } }
        ],
        barWidth: 20,
        label: {
          show: true,
          position: 'right',
          formatter: '{c}%',
          color: muted,
          fontSize: 11
        },
        itemStyle: { borderRadius: [0, 4, 4, 0] }
      }
    ]
  });
  window.addEventListener('resize', function() { impact.resize(); });
})();
