/**
 * 金水谣 ECharts 统一主题
 * ─────────────────────────────────────────────────────────
 * 主题名称：jinshuiyao
 * 设计风格：深海熔金暗色主题（与 control-center 配色体系一致）
 * 用法：在 echarts.min.js 之后引入本文件，然后使用
 *       echarts.init(dom, 'jinshuiyao') 即可应用统一风格。
 *
 * 配色说明：
 *   主色系 —— 蓝 / 紫 / 绿 / 琥珀 / 青 / 玫红
 *   背景   —— 透明（适配各页面自身的深色背景）
 *   文字   —— 浅灰 #b0b8c8（图例）/ #8892a8（刻度标签）
 *   坐标轴 —— 轴线 #3a4560
 * ─────────────────────────────────────────────────────────
 */
(function (root, factory) {
  if (typeof echarts === 'undefined') {
    console.warn('[jinshuiyao-echarts-theme] 未检测到 echarts，请先引入 echarts.min.js');
    return;
  }
  factory(echarts);
})(this, function (echarts) {

  echarts.registerTheme('jinshuiyao', {

    /* ── 全局 ── */
    color: [
      '#2f6df0',  // 主蓝
      '#7c5cff',  // 紫
      '#16a34a',  // 绿
      '#f0a020',  // 琥珀
      '#00d4aa',  // 青
      '#f43f5e'   // 玫红
    ],
    backgroundColor: 'transparent',

    /* ── 文字 ── */
    textStyle: {
      fontFamily: "'Noto Sans SC', 'Microsoft YaHei', sans-serif",
      color: '#b0b8c8'
    },

    /* ── 标题 ── */
    title: {
      textStyle: {
        color: '#e2e8f0',
        fontSize: 16,
        fontWeight: 600
      },
      subtextStyle: {
        color: '#8892a8',
        fontSize: 12
      }
    },

    /* ── 图例 ── */
    legend: {
      textStyle: {
        color: '#b0b8c8',
        fontSize: 12
      },
      inactiveColor: '#4a5568'
    },

    /* ── 提示框 ── */
    tooltip: {
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderColor: 'rgba(58, 69, 96, 0.6)',
      borderWidth: 1,
      borderRadius: 8,
      padding: [10, 14],
      textStyle: {
        color: '#e2e8f0',
        fontSize: 13
      },
      extraCssText: 'box-shadow: 0 4px 20px rgba(0,0,0,0.4); backdrop-filter: blur(4px);'
    },

    /* ── 类目坐标轴 ── */
    categoryAxis: {
      axisLine: {
        show: true,
        lineStyle: { color: '#3a4560' }
      },
      axisTick: {
        show: true,
        lineStyle: { color: '#3a4560' }
      },
      axisLabel: {
        color: '#8892a8',
        fontSize: 11
      },
      splitLine: {
        show: false,
        lineStyle: { color: ['#2a3450'] }
      },
      splitArea: {
        show: false
      }
    },

    /* ── 数值坐标轴 ── */
    valueAxis: {
      axisLine: {
        show: false,
        lineStyle: { color: '#3a4560' }
      },
      axisTick: {
        show: false,
        lineStyle: { color: '#3a4560' }
      },
      axisLabel: {
        color: '#8892a8',
        fontSize: 11
      },
      splitLine: {
        show: true,
        lineStyle: { color: ['#2a3450'], type: 'dashed' }
      },
      splitArea: {
        show: false
      }
    },

    /* ── 对数坐标轴 ── */
    logAxis: {
      axisLine: {
        show: false,
        lineStyle: { color: '#3a4560' }
      },
      axisLabel: {
        color: '#8892a8',
        fontSize: 11
      },
      splitLine: {
        show: true,
        lineStyle: { color: ['#2a3450'], type: 'dashed' }
      }
    },

    /* ── 时间坐标轴 ── */
    timeAxis: {
      axisLine: {
        show: true,
        lineStyle: { color: '#3a4560' }
      },
      axisLabel: {
        color: '#8892a8',
        fontSize: 11
      },
      splitLine: {
        show: false,
        lineStyle: { color: ['#2a3450'] }
      }
    },

    /* ── 折线图 ── */
    line: {
      smooth: true,
      symbolSize: 4,
      lineStyle: { width: 2 }
    },

    /* ── 柱状图 ── */
    bar: {
      barMaxWidth: 40,
      itemStyle: {
        borderRadius: [3, 3, 0, 0]
      }
    },

    /* ── 饼图 ── */
    pie: {
      itemStyle: {
        borderColor: 'rgba(15, 23, 42, 0.8)',
        borderWidth: 2
      }
    },

    /* ── 雷达图 ── */
    radar: {
      axisName: {
        color: '#b0b8c8',
        fontSize: 11
      },
      splitLine: {
        lineStyle: { color: '#2a3450' }
      },
      splitArea: {
        areaStyle: { color: ['transparent', 'rgba(42, 52, 80, 0.3)'] }
      },
      axisLine: {
        lineStyle: { color: '#3a4560' }
      }
    },

    /* ── 仪表盘 ── */
    gauge: {
      axisLine: {
        lineStyle: { color: [[1, '#3a4560']] }
      },
      axisTick: {
        lineStyle: { color: '#8892a8' }
      },
      axisLabel: {
        color: '#8892a8'
      },
      detail: {
        color: '#e2e8f0'
      }
    },

    /* ── 数据缩放 ── */
    dataZoom: {
      backgroundColor: 'rgba(15, 23, 42, 0.6)',
      dataBackgroundColor: 'rgba(47, 109, 240, 0.3)',
      fillerColor: 'rgba(47, 109, 240, 0.15)',
      handleColor: '#2f6df0',
      handleSize: '100%',
      textStyle: { color: '#8892a8' }
    },

    /* ── 视觉映射 ── */
    visualMap: {
      textStyle: { color: '#8892a8' }
    },

    /* ── 工具箱 ── */
    toolbox: {
      iconStyle: {
        borderColor: '#8892a8'
      },
      emphasis: {
        iconStyle: {
          borderColor: '#2f6df0'
        }
      }
    }
  });

});
