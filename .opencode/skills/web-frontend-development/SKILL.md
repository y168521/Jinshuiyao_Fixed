---
name: web-frontend-development
description: Web前端开发技能，含ECharts高级配置、响应式布局、Flask+AJAX交互、仪表盘设计规范。使用场景：数据可视化仪表盘开发、前端页面开发、ECharts图表定制、响应式布局适配、前后端交互。
---

# Web前端开发技能

## 技术栈
- **基础**：HTML5 / CSS3 / JavaScript (ES6+)
- **图表**：ECharts 5.x
- **后端交互**：Fetch API / AJAX
- **布局**：Flex / Grid / 响应式

## ECharts 高级配置

### 常用图表类型
- 折线图：趋势变化
- 柱状图：对比分析
- 饼图/环形图：占比
- 散点图：相关性
- 热力图：密度分布
- 雷达图：多维对比
- 仪表盘：进度/完成率

### 配置优化技巧
1. **大数据量优化**：
   - 开启 sampling 降采样
   - 用 Canvas 不用 SVG
   - 数据分片加载

2. **交互增强**：
   - tooltip 自定义格式
   - dataZoom 缩放拖动
   - legend 点击切换显示
   - 点击事件联动其他图表

3. **视觉优化**：
   - 渐变色填充
   - 阴影效果
   - 自定义标记线/标记点
   - 动画效果

### 仪表盘设计规范
- 顶部：关键指标卡片（KPI）
- 中部：主图表（最大的图，核心信息）
- 底部：次图表/明细表
- 配色：不超过6种颜色，主色+辅助色+中性色

## 响应式布局

### 移动端优先
- 先写小屏幕样式，再用 min-width 往大屏幕扩展
- 断点：768px（平板）、1024px（桌面）、1440px（大屏）

### Flex 布局
```css
.container {
  display: flex;
  justify-content: space-between; /* 主轴对齐 */
  align-items: center; /* 交叉轴对齐 */
  flex-wrap: wrap; /* 换行 */
}
```

### Grid 布局
```css
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
}
```

## Flask + AJAX 交互

### 后端接口
```python
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/api/data')
def get_data():
    # 获取参数
    period = request.args.get('period', 30)
    # 返回JSON
    return jsonify({
        "code": 200,
        "data": { ... }
    })
```

### 前端调用
```javascript
async function loadData() {
  const res = await fetch('/api/data?period=30');
  const json = await res.json();
  if (json.code === 200) {
    renderChart(json.data);
  }
}
```

### 最佳实践
- 统一响应格式：code + msg + data
- 加载状态：loading 提示
- 错误处理：请求失败提示
- 防抖节流：频繁触发的接口加防抖

## 性能优化

### 加载优化
- 静态资源 CDN
- 图片懒加载
- 代码分割
- 压缩（gzip）

### 渲染优化
- 减少 DOM 操作
- 虚拟列表（大数据量表格）
- 防抖节流
- requestAnimationFrame

## 参考资料

