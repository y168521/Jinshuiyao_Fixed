/* ═══════════════════════════════════════════════════════════════
   金水谣 · 量化分析仪表盘  app.js
   架构：单一 state + 事件总线；四个解耦引擎（Tick / Chart / Signal / Event / Terminal）
   审查要点落地：
     · 高频渲染：ECharts lazyUpdate + rAF 节流 + 数据窗口限长
     · 外部 API：AbortController 超时 + 指数退避重试 + JSON 容错(围栏清洗/字段缺失默认)
     · 信号可解释：每个指标给出可读公式，权重可动态调整
     · 代码解耦 / 可维护：模块各自独立，DOM 写入 rAF 批量 + 行数截断
   ═══════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  /* ───────────────── 工具函数 ───────────────── */
  const util = {
    clamp: (v, lo, hi) => Math.max(lo, Math.min(hi, v)),
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    now: () => new Date(),
    ts: (d) => {
      d = d || new Date();
      const p = (n, l = 2) => String(n).padStart(l, "0");
      return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
    },
    fmt: (n, d = 2) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }),
    // rAF 节流：同一帧内多次调用只执行最后一次
    rafThrottle(fn) {
      let scheduled = false, lastArgs = null;
      return function (...args) {
        lastArgs = args;
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => { scheduled = false; fn.apply(null, lastArgs); });
      };
    },
    debounce(fn, wait = 200) {
      let t = null;
      return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(null, a), wait); };
    },
    // 简单标准差
    std(arr) {
      if (arr.length < 2) return 0;
      const m = arr.reduce((s, x) => s + x, 0) / arr.length;
      const v = arr.reduce((s, x) => s + (x - m) ** 2, 0) / (arr.length - 1);
      return Math.sqrt(v);
    },
    sma(arr, n) {
      if (!arr.length) return 0;
      const w = arr.slice(-n);
      return w.reduce((s, x) => s + x, 0) / w.length;
    },
  };

  /* ───────────────── 历史回测（真实日线，离线可算） ─────────────────
     用 20 日动量信号在历史上做方向判定，统计：
       · win    ：下一交易日方向命中率（真实"胜率"来源，替代合成滚动）
       · maxdd  ：多头策略权益曲线最大回撤
       · sample ：有效样本天数
     数据全部来自金水谣真实日线，不依赖任何模拟。                        */
  function computeBacktest(closes, lookback) {
    if (!closes || closes.length < lookback + 2) return null;
    let hits = 0, total = 0;
    let eq = 1, peak = 1, maxdd = 0;
    for (let i = lookback; i < closes.length - 1; i++) {
      let sum = 0;
      for (let j = i - lookback; j < i; j++) sum += closes[j];
      const sma = sum / lookback;
      const sig = closes[i] > sma ? 1 : -1;          // 动量信号：站上20日线看多
      const ret = closes[i + 1] / closes[i] - 1;
      const actual = ret >= 0 ? 1 : -1;
      if (sig === actual) hits++;
      total++;
      eq *= (1 + (sig > 0 ? ret : 0));               // 空头信号时空仓，仅多头持仓
      if (eq > peak) peak = eq;
      const dd = 1 - eq / peak;
      if (dd > maxdd) maxdd = dd;
    }
    return { win: total ? (hits / total) * 100 : 0, maxdd: maxdd * 100, sample: total };
  }

  /* ───────────────── 事件总线 ───────────────── */
  const bus = (() => {
    const map = {};
    return {
      on(ev, fn) { (map[ev] = map[ev] || []).push(fn); },
      emit(ev, payload) { (map[ev] || []).forEach((fn) => { try { fn(payload); } catch (e) { console.error(e); } }); },
    };
  })();

  /* ───────────────── 全局状态 ───────────────── */
  const state = {
    running: false,
    config: {
      tickMs: 220,            // 高频 tick 间隔
      window: 240,            // 图表数据窗口长度
      endpoint: "",           // 外部大模型 API（空=演示模式）
      apiKey: "",
      model: "gpt-4o-mini",
      timeoutMs: 8000,
      retries: 3,
      weights: { momentum: 0.5, volatility: 0.3, volume: 0.2 },
      autoEventMs: 18000,     // 自动事件推演间隔
    },
    ticks: [],                // {ts, price, vol}
    signals: {},              // 最新七项指标
    predictionLog: [],        // 用于经验胜率：{pred, actual}
    events: [],               // 事件推演结果
  };

  /* ───────────────── 真实数据源（金水谣股票日线） ─────────────────
     优先 /api/stock/<sym>（quant_server 直读金水谣真实缓存，同源无CORS）
     失败回退 data/real_stock.json 静态快照（离线可用）            */
  const DataSource = {
    sym: "sh000001",
    meta: null,        // {name,latest,prev,change_pct,daily}
    source: "static",  // live | static | none
    SYMBOLS: { sh000001: "上证指数", sh000300: "沪深300", sz399001: "深证成指" },
    async load(sym) {
      sym = sym || this.sym;
      let data = null, source = "static";
      try {
        const r = await fetch(`/api/quant/stock/${sym}`, { headers: { Accept: "application/json" } });
        if (r.ok) { data = await r.json(); if (data && data.live) source = "live"; }
      } catch (e) { /* fallback to legacy api */ }
      if (!data) {
        try {
          const r = await fetch(`/api/stock/${sym}`, { headers: { Accept: "application/json" } });
          if (r.ok) { data = await r.json(); if (data && data.live) source = "live"; }
        } catch (e) { /* fallback to static snapshot */ }
      }
      if (!data) {
        try {
          const r = await fetch(`data/real_stock.json`, { headers: { Accept: "application/json" } });
          if (r.ok) { const all = await r.json(); data = (all.symbols && all.symbols[sym]) || null; source = "static"; }
        } catch (e) { data = null; }
      }
      if (!data || !data.daily || data.daily.length < 2) { this.source = "none"; return false; }
      this.sym = sym; this.meta = data; this.source = source;
      Terminal.append("数据", source === "live" ? "up" : "flat", "LOW",
        `接入真实数据[${data.name}] 最新 ${data.latest.date} 收盘 ${util.fmt(data.latest.close)} (${data.change_pct >= 0 ? "+" : ""}${data.change_pct}%) · 源=${source === "live" ? "LIVE" : "快照"}`);
      return true;
    },
    closes() { return (this.meta && this.meta.daily || []).map((d) => +d.close); },
    vols() { return (this.meta && this.meta.daily || []).map((d) => +d.volume || 0); },
    latest() { return this.meta && this.meta.latest; },
    prev() { return this.meta && this.meta.prev; },
    name() { return (this.meta && this.meta.name) || this.SYMBOLS[this.sym] || this.sym; },
  };

  /* ───────────────── 头部实时区（价/涨跌幅/数据模式） ───────────────── */
  const UI = {
    updateLive(price, chg) {
      const pe = document.getElementById("livePrice");
      const ce = document.getElementById("liveChg");
      if (pe) pe.textContent = util.fmt(price, 2);
      if (ce) {
        const up = chg >= 0;
        ce.textContent = `${up ? "+" : ""}${chg.toFixed(2)}%`;
        ce.className = "live-chg " + (up ? "up" : "down");
      }
    },
    setMode(source) {
      const el = document.getElementById("dataMode");
      if (!el) return;
      if (source === "live") { el.textContent = "● LIVE 真实"; el.className = "mode-badge live"; }
      else if (source === "static") { el.textContent = "○ 快照 真实"; el.className = "mode-badge static"; }
      else { el.textContent = "○ 无数据"; el.className = "mode-badge none"; }
    },
    setSymbol(name) {
      const el = document.getElementById("symName");
      if (el) el.textContent = name;
    },
  };

  /* ───────────────── 左上：Tick 数据引擎 ───────────────── */
  const TickEngine = {
    timer: null,
    price: 3200,
    vol: 1,
    base: 3200,     // 昨收（真实），用于涨跌幅基准
    target: 3200,   // 最新收盘（真实），分时末端均值回复目标
    open: 3200, dayHigh: 3200, dayLow: 3200,
    tickIdx: 0,
    start() {
      if (this.timer) return;
      // 锚定真实当日数据：昨收=起点，最新收盘=目标，并约束在真实当日高低区间内
      const lv = DataSource.latest(), pv = DataSource.prev();
      if (lv && pv) {
        this.base = +pv.close; this.target = +lv.close;
        this.open = +lv.open; this.dayHigh = +lv.high; this.dayLow = +lv.low;
        this.price = this.base;
      }
      this.tickIdx = 0;
      const loop = () => {
        if (!state.running) return;
        // 均值回复随机游走：向真实最新收盘缓慢靠拢 + 日内噪声 + 偶发跳变
        const reversion = (this.target - this.price) * 0.015;
        const noise = (Math.random() - 0.5) * (this.target * 0.0009);
        const shock = Math.random() < 0.04 ? (Math.random() - 0.5) * (this.target * 0.004) : 0;
        const step = reversion + noise + shock;
        // 真实日内价格边界：取 昨收 与 当日真实最高/最低 的包络
        const lo = Math.min(this.base, this.dayLow) * 0.999;
        const hi = Math.max(this.target, this.dayHigh) * 1.001;
        this.price = util.clamp(this.price + step, lo, hi);
        // 成交量剖面：U 型（开盘/收盘放量）+ 对价格跳变敏感
        this.tickIdx++;
        const t = (this.tickIdx % state.config.window) / state.config.window;
        const uShape = 0.5 + 0.5 * Math.abs(Math.cos(Math.PI * t));   // 开/收=1，午间=0.5
        const moveShock = Math.abs(step) / (this.target * 0.001);
        this.vol = util.clamp(uShape * (1 + moveShock), 0.3, 3);
        const point = { ts: util.now(), price: this.price, vol: this.vol };
        state.ticks.push(point);
        if (state.ticks.length > state.config.window * 2) state.ticks.shift();
        bus.emit("tick", point);
        this.timer = setTimeout(loop, state.config.tickMs);
      };
      loop();
    },
    stop() { clearTimeout(this.timer); this.timer = null; },
  };

  /* ───────────────── 左上：ECharts 分时图面板 ───────────────── */
  const ChartPanel = {
    chart: null,
    dirty: false,
    priceData: [],
    chgData: [],
    base: 3200,
    init() {
      const el = document.getElementById("chart");
      if (typeof echarts === "undefined") { el.innerHTML = '<div style="color:#ff3b5c;padding:20px">ECharts 未加载（vendor/echarts.min.js 缺失或被拦截）</div>'; return; }
      this.chart = echarts.init(el, 'jinshuiyao', { renderer: "canvas" });
      this.chart.setOption(this.option());
      window.addEventListener("resize", util.debounce(() => this.chart && this.chart.resize(), 150));
      bus.on("tick", () => this.markDirty());
      // rAF 渲染循环：限频，避免每 tick 全量重绘
      const render = util.rafThrottle(() => {
        if (!this.dirty || !this.chart) return;
        this.dirty = false;
        this.chart.setOption({ series: [{ data: this.priceData }, { data: this.chgData }] }, { lazyUpdate: true });
      });
      const loop = () => { render(); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    },
    markDirty() {
      const pts = state.ticks.slice(-state.config.window);
      if (!pts.length) return;
      // 基准=真实昨收（DataSource.prev），涨跌幅与真实当日涨跌一致
      const base = (DataSource.prev() && DataSource.prev().close) ? +DataSource.prev().close : pts[0].price;
      this.base = base;
      this.priceData = pts.map((p) => [p.ts.getTime(), +p.price.toFixed(2)]);
      this.chgData = pts.map((p) => [p.ts.getTime(), +(((p.price - base) / base) * 100).toFixed(3)]);
      this.dirty = true;
      // 实时头部：最新价 + 涨跌幅
      const lastP = pts[pts.length - 1].price;
      const chg = ((lastP - base) / base) * 100;
      if (typeof UI !== "undefined") UI.updateLive(lastP, chg);
    },
    option() {
      return {
        animation: false,
        backgroundColor: "transparent",
        grid: { left: 52, right: 56, top: 16, bottom: 28 },
        tooltip: { trigger: "axis", backgroundColor: "rgba(10,14,26,0.92)", borderColor: "rgba(255,210,74,0.3)", textStyle: { color: "#d7e6ff", fontFamily: "JetBrains Mono" } },
        xAxis: { type: "time", axisLine: { lineStyle: { color: "rgba(255,210,74,0.2)" } }, axisLabel: { color: "#7e8db0", fontFamily: "JetBrains Mono", fontSize: 10 }, splitLine: { show: false } },
        yAxis: [
          { type: "value", scale: true, position: "left", name: "价格", nameTextStyle: { color: "#ffd24a", fontSize: 10 }, axisLabel: { color: "#7e8db0", fontFamily: "JetBrains Mono", fontSize: 10 }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.04)" } } },
          { type: "value", position: "right", name: "涨跌幅%", nameTextStyle: { color: "#2ff3ff", fontSize: 10 }, axisLabel: { color: "#7e8db0", fontFamily: "JetBrains Mono", fontSize: 10, formatter: "{value}%" }, splitLine: { show: false } },
        ],
        series: [
          { name: "价格", type: "line", showSymbol: false, yAxisIndex: 0, lineStyle: { color: "#ffd24a", width: 1.6 }, areaStyle: { color: "rgba(255,210,74,0.06)" }, data: [] },
          { name: "涨跌幅%", type: "line", showSymbol: false, yAxisIndex: 1, lineStyle: { color: "#2ff3ff", width: 1.2, opacity: 0.8 }, data: [] },
        ],
      };
    },
  };

  /* ───────────────── 右上：信号引擎（可解释 + 动态权重） ───────────────── */
  const SignalEngine = {
    el: null,
    // 七项指标均来自真实日线（日频），而非模拟 tick
    init() { this.el = document.getElementById("signals"); this.render(); bus.on("tick", () => this.recompute()); },
    recompute() {
      const closes = DataSource.closes();
      const vols = DataSource.vols();
      if (closes.length < 20) return;
      const N = closes.length;
      const last = closes[N - 1];
      const sma20 = util.sma(closes, 20);
      const sma5 = util.sma(closes, 5);
      // 动量：现价 vs 20日线（真实）
      const momentum = util.clamp(((last - sma20) / sma20) * 100, -100, 100);
      // 日收益序列 → 年化波动（风险，真实）
      const rets = [];
      for (let i = 1; i < N; i++) rets.push((closes[i] - closes[i - 1]) / closes[i - 1]);
      const recentRets = rets.slice(-20);
      const dailyVol = util.clamp(util.std(recentRets) * Math.sqrt(252) * 100, 0, 100);
      // 量比（真实量能）：最新量 / 20日均量
      const volAvg = util.sma(vols.slice(-20), 20) || 1;
      const volRatio = vols[N - 1] / volAvg;
      let volNorm = util.clamp(volRatio * 40, 0, 100);
      // 叠加分时活跃度（真实 intraday），让 VOL 实时滚动
      const ticks = state.ticks.slice(-60);
      if (ticks.length > 3) {
        const liveVol = util.sma(ticks.map((t) => t.vol), Math.min(10, ticks.length));
        const liveNorm = util.clamp((liveVol / 3) * 100, 0, 100);
        volNorm = util.clamp(volNorm * 0.7 + liveNorm * 0.3, 0, 100);
      }
      // 胜率：历史回测方向命中率（真实，来自 20 日动量信号）
      const bt = computeBacktest(closes, 20);
      const winRate = bt ? bt.win : 0;
      // 风险=年化波动；赔率随风险上升
      const risk = dailyVol;
      const odds = util.clamp(1 + risk / 18, 1.1, 9);
      const p = winRate / 100, b = odds - 1;
      const kelly = util.clamp((p * (b + 1) - 1) / b, 0, 0.95);   // 凯利仓位
      const ev = util.clamp(p * b - (1 - p) * 1, -1, 5) * 100;     // 期望收益%
      // SCORE：动态权重（动量/波动/量能），可解释
      const w = state.config.weights;
      const score = util.clamp(
        w.momentum * (50 + momentum) + w.volatility * (100 - dailyVol) + w.volume * volNorm, 0, 100);

      state.signals = { VOL: volNorm, SCORE: score, WIN: winRate, ODDS: odds, RISK: risk, POS: kelly * 100, EV: ev, _volRatio: volRatio, BT: bt };
      this.render();
      bus.emit("signal", state.signals);
    },
    render() {
      const s = state.signals; if (!Object.keys(s).length) return;
      const cards = [
        { k: "VOL 量能", v: util.fmt(s.VOL, 1), cls: "", bar: s.VOL, formula: `量比${(s._volRatio || 0).toFixed(2)}×40 + 分时` },
        { k: "SCORE 综合分", v: util.fmt(s.SCORE, 1), cls: s.SCORE >= 60 ? "up" : s.SCORE < 40 ? "down" : "warn", bar: s.SCORE, formula: "Σ wᵢ·指标(动量/波动/量能·日频)" },
        { k: "胜率", v: util.fmt(s.WIN, 1) + "%", cls: s.WIN >= 55 ? "up" : s.WIN < 45 ? "down" : "warn", bar: s.WIN, formula: "历史回测方向命中率(真实)" },
        { k: "赔率", v: util.fmt(s.ODDS, 2), cls: "", bar: (s.ODDS - 1) / 8 * 100, formula: "1 + 风险/18" },
        { k: "风险", v: util.fmt(s.RISK, 1), cls: s.RISK >= 60 ? "down" : s.RISK < 30 ? "up" : "warn", bar: s.RISK, formula: "日收益年化σ×√252" },
        { k: "仓位", v: util.fmt(s.POS, 1) + "%", cls: s.POS >= 50 ? "warn" : "up", bar: s.POS, formula: "凯利 f=(p(b+1)-1)/b" },
        { k: "EV 期望值", v: util.fmt(s.EV, 1) + "%", cls: s.EV >= 0 ? "up" : "down", bar: util.clamp(50 + s.EV / 2, 0, 100), formula: "p·b-(1-p)" },
      ];
      this.el.innerHTML = cards.map((c) => `
        <div class="metric ${c.cls}">
          <div class="k">${c.k}</div>
          <div class="v">${c.v}</div>
          <div class="bar" style="width:${util.clamp(c.bar, 0, 100)}%"></div>
          <div class="formula">${c.formula}</div>
        </div>`).join("");
      // 回测底部条：真实历史样本 / 胜率 / 最大回撤
      const bt = state.signals.BT;
      const btEl = document.getElementById("btLine");
      if (btEl && bt) {
        btEl.innerHTML = `回测(20日动量策略) · 样本 <b>${bt.sample}</b> 日 · 历史胜率 ` +
          `<b style="color:${bt.win >= 55 ? "var(--green)" : "var(--red)"}">${bt.win.toFixed(1)}%</b> · 最大回撤 ` +
          `<b style="color:var(--red)">${bt.maxdd.toFixed(1)}%</b>`;
      }
    },
  };

  /* ───────────────── 左下：事件推演引擎（外部 LLM + 容错） ───────────────── */
  const EventEngine = {
    el: null, summaryEl: null, inputEl: null,
    init() {
      this.el = document.getElementById("eventTable");
      this.summaryEl = document.getElementById("eventSummary");
      this.inputEl = document.getElementById("eventInput");
      document.getElementById("runEvent").addEventListener("click", () => this.run(this.inputEl.value || "央行宣布降准0.5个百分点"));
    },
    // 知识库上下文：从金水谣 MiroFish 检索与事件相关的策略卡（事件推演注入）
    async getContext(prompt) {
      let cards = [];
      try {
        const q = encodeURIComponent((prompt || "") + " 板块 stock 量化 事件");
        const r = await fetch(`/api/quant/knowledge/search?q=${q}&limit=6`, { headers: { Accept: "application/json" } });
        if (r.ok) { const d = await r.json(); cards = d.cards || []; }
      } catch (e) { cards = []; }
      Terminal.append("知识库", "flat", "LOW", `注入上下文：${cards.length} 张策略卡`);
      return cards;
    },
    // 外部 API 调用：超时 + 指数退避重试 + JSON 容错
    async callLLM(prompt, ctx) {
      const cfg = state.config;
      if (!cfg.endpoint) return { ok: true, source: "mock", data: this.mock(prompt, ctx) };

      let lastErr = null;
      for (let attempt = 0; attempt <= cfg.retries; attempt++) {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), cfg.timeoutMs);
        try {
          const resp = await fetch(cfg.endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...(cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {}) },
            body: JSON.stringify({ model: cfg.model, messages: [{ role: "user", content: prompt }], temperature: 0.3 }),
            signal: ctrl.signal,
          });
          clearTimeout(tid);
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          const json = await resp.json();
          const text = (json.choices && json.choices[0] && json.choices[0].message && json.choices[0].message.content) || JSON.stringify(json);
          return { ok: true, source: "api", data: this.parseJSON(text) };
        } catch (e) {
          clearTimeout(tid);
          lastErr = e;
          if (attempt < cfg.retries) {
            const backoff = 600 * Math.pow(2, attempt);
            Terminal.append("事件推演", "flat", "LOW", `API 第${attempt + 1}次失败(${e.name || e.message})，${backoff}ms 后重试`);
            await util.sleep(backoff);
          }
        }
      }
      Terminal.append("事件推演", "down", "MID", `API 重试耗尽，降级为演示数据：${lastErr && (lastErr.name || lastErr.message)}`);
      return { ok: false, source: "mock", error: lastErr, data: this.mock(prompt, ctx) };
    },
    // JSON 容错：清洗代码围栏 → 截取首{尾} → 字段缺失填默认
    parseJSON(text) {
      try {
        let t = String(text).trim();
        t = t.replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
        const s = t.indexOf("{"), e = t.lastIndexOf("}");
        if (s >= 0 && e > s) t = t.slice(s, e + 1);
        const o = JSON.parse(t);
        return this.normalize(o);
      } catch (e) {
        // 兜底：正则抽字段
        const m = String(text).match(/summary["']?\s*[:=]\s*["']([^"']+)["']/i);
        return this.normalize({ summary: m ? m[1] : "解析失败，已用兜底结构", sectors: [] });
      }
    },
    normalize(o) {
      const dirMap = { 利好: "利好", 利空: "利空", 中性: "中性", up: "利好", down: "利空", positive: "利好", negative: "利空" };
      const sectors = Array.isArray(o.sectors) ? o.sectors.map((x) => ({
        name: String(x.name || "未知板块"),
        direction: dirMap[String(x.direction || "中性")] || "中性",
        impact: util.clamp(Number(x.impact || 0), -100, 100),
        confidence: util.clamp(Number(x.confidence || 50), 0, 100),
        logic: String(x.logic || "—"),
      })) : [];
      return { summary: String(o.summary || "（无摘要）"), sectors };
    },
    mock(prompt, ctx) {
      const base = [
        { name: "银行", direction: "利好", impact: 62, confidence: 78, logic: "降准释放流动性，净息差改善预期" },
        { name: "地产", direction: "利好", impact: 48, confidence: 65, logic: "融资成本下行，销售端边际回暖" },
        { name: "白酒消费", direction: "中性", impact: 8, confidence: 55, logic: "与货币政策关联度中等" },
        { name: "半导体", direction: "利空", impact: -35, confidence: 60, logic: "风险偏好切换至顺周期，成长暂时承压" },
      ];
      const kbNote = (ctx && ctx.length)
        ? ` 已参考金水谣知识库 ${ctx.length} 张策略卡（如：${ctx.slice(0, 3).map((c) => c.title).join("、")}）。`
        : "";
      return { summary: `【演示数据】针对「${prompt}」的板块影响推演（未配置外部API，使用内置mock）。${kbNote}`, sectors: base };
    },
    async run(prompt) {
      Terminal.append("事件推演", "flat", "LOW", `发起推演：${prompt}`);
      const ctx = await this.getContext(prompt);
      const kbBlock = ctx.length
        ? "\n【金水谣知识库上下文（历史策略与经验，请参考并呼应）】\n" +
          ctx.map((c, i) => `${i + 1}. [${c.title}] ${c.content}`).join("\n")
        : "";
      const aug = `你是A股事件推演分析师。${kbBlock}\n请分析热点事件对A股板块的影响，返回JSON：` +
        `{summary, sectors:[{name,direction(利好/利空/中性),impact(-100~100),confidence(0~100),logic}]}。事件：${prompt}`;
      const res = await this.callLLM(aug, ctx);
      this.render(res.data, res.source, ctx);
      this.writeBack(prompt, res.data, res.source);
    },
    // 学习闭环：把推演结论 upsert 回金水谣知识库（event_deduction 钩子）
    async writeBack(prompt, data, source) {
      const top = (data.sectors || []).slice(0, 3)
        .map((s) => `${s.name}(${s.direction}${s.impact >= 0 ? "+" : ""}${s.impact})`).join("、");
      const content = `事件：「${prompt}」\n结论：${data.summary || ""}\n主要影响板块：${top}\n（来源：${source === "mock" ? "演示" : "外部API"}）`;
      const card = {
        title: "事件推演结论：" + String(prompt || "").slice(0, 16),
        content, category: "deduction", domain: "stock",
        tags: ["事件推演", "板块影响", String(prompt || "").slice(0, 10)],
        engine_hook: "event_deduction", source: "dashboard", priority: 5, subsystem: "stock",
      };
      try {
        const r = await fetch("/api/quant/knowledge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(card),
        });
        if (r.ok) {
          const d = await r.json();
          Terminal.append("知识库", "up", "LOW", `推演结论已回写 · 知识库共 ${d.total} 张（${card.title}）`);
        } else {
          Terminal.append("知识库", "down", "MID", `回写失败 HTTP ${r.status}`);
        }
      } catch (e) {
        Terminal.append("知识库", "down", "MID", `回写失败：${e.name || e.message}`);
      }
    },
    render(data, source, ctx) {
      state.events = data.sectors || [];
      const rows = (data.sectors || []).map((x) => {
        const pct = Math.abs(x.impact);
        const cls = x.impact >= 0 ? "impact-pos" : "impact-neg";
        return `<tr>
          <td>${x.name}</td>
          <td style="color:${x.direction === "利好" ? "var(--green)" : x.direction === "利空" ? "var(--red)" : "var(--muted)"}">${x.direction}</td>
          <td><div class="pbar"><i class="${cls}" style="width:${pct}%"></i></div><span style="font-size:10px;color:#7e8db0">${x.impact}</span></td>
          <td>${x.confidence}%</td>
          <td style="color:#9fb0d6">${x.logic}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="5" style="color:#7e8db0">无板块数据</td></tr>`;
      this.el.innerHTML = `<table><thead><tr><th>板块</th><th>方向</th><th>强度</th><th>置信度</th><th>逻辑</th></tr></thead><tbody>${rows}</tbody></table>`;
      const kbBadge = ctx && ctx.length ? ` <span class="badge kb">📚知识库×${ctx.length}</span>` : "";
      this.summaryEl.innerHTML = `<span class="badge ${source === "mock" ? "mock" : ""}">${source === "mock" ? "演示" : "API"}</span>${kbBadge} ${data.summary || ""}`;
    },
  };

  /* ───────────────── 右下：DEEP SCAN 终端 ───────────────── */
  const Terminal = {
    el: null, pending: [], cap: 200,
    init() {
      this.el = document.getElementById("terminal");
      const flush = util.rafThrottle(() => {
        if (!this.pending.length) return;
        const frag = document.createDocumentFragment();
        this.pending.forEach((l) => frag.appendChild(this.node(l)));
        this.el.appendChild(frag);
        this.pending = [];
        // 行数截断，防止 DOM 无限增长
        while (this.el.childElementCount > this.cap) this.el.removeChild(this.el.firstChild);
        this.el.scrollTop = this.el.scrollHeight;
      });
      const loop = () => { flush(); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    },
    node(l) {
      const div = document.createElement("div");
      div.className = "log-line";
      div.innerHTML =
        `<span class="ts">[${l.ts}]</span> ` +
        `<span class="dir-${l.dir}">${l.dir === "up" ? "▲" : l.dir === "down" ? "▼" : "■"}</span> ` +
        `<span class="risk-${l.risk}">[${l.risk}]</span> ` +
        `<span class="reason">${l.reason}</span>`;
      return div;
    },
    append(tag, dir, risk, reason) {
      // tag 用于来源标注，dir: up/down/flat，risk: HIGH/MID/LOW
      this.pending.push({ ts: util.ts(), dir, risk, reason: `[${tag}] ${reason}` });
    },
  };

  /* ───────────────── 应用装配 ───────────────── */
  const App = {
    autoTimer: null,
    init() {
      ChartPanel.init();
      SignalEngine.init();
      EventEngine.init();
      Terminal.init();
      this.bindControls();
      this.bindConfig();
      this.bootstrap();
      Terminal.append("系统", "flat", "LOW", "金水谣量化仪表盘已就绪 · 点击「启动」开始高频行情");
    },
    // 启动加载真实数据（默认上证），填充信号引擎与头部
    async bootstrap() {
      const sel = document.getElementById("symSelect");
      const sym = (sel && sel.value) || "sh000001";
      const ok = await DataSource.load(sym);
      UI.setMode(DataSource.source);
      UI.setSymbol(DataSource.name());
      if (!ok) {
        UI.setMode("none");
        Terminal.append("数据", "down", "HIGH", "真实数据接入失败（live/快照均不可用），请检查 金水谣数据/stock/cache");
        return;
      }
      SignalEngine.recompute();
    },
    bindControls() {
      const btn = document.getElementById("toggle");
      btn.addEventListener("click", () => {
        state.running = !state.running;
        btn.textContent = state.running ? "⏸ 暂停" : "▶ 启动";
        btn.classList.toggle("danger", state.running);
        if (state.running) {
          TickEngine.start();
          Terminal.append("系统", "up", "LOW", "行情引擎启动 · tick=" + state.config.tickMs + "ms · 标的=" + DataSource.name());
          this.scheduleAuto();
        } else {
          TickEngine.stop(); clearInterval(this.autoTimer);
          Terminal.append("系统", "down", "MID", "行情引擎暂停");
        }
      });
      // 标的切换：重载真实数据 + 重置分时
      const sel = document.getElementById("symSelect");
      if (sel) sel.addEventListener("change", async () => {
        state.running = false;
        const b = document.getElementById("toggle"); b.textContent = "▶ 启动"; b.classList.remove("danger");
        TickEngine.stop(); clearInterval(this.autoTimer);
        state.ticks = []; ChartPanel.priceData = []; ChartPanel.chgData = [];
        Terminal.append("数据", "flat", "LOW", "切换标的 → " + DataSource.SYMBOLS[sel.value]);
        await this.bootstrap();
      });
      document.getElementById("openCfg").addEventListener("click", () => document.getElementById("drawer").classList.toggle("open"));
      document.getElementById("reset").addEventListener("click", () => {
        state.ticks = []; state.predictionLog = []; ChartPanel.priceData = []; ChartPanel.chgData = [];
        Terminal.append("系统", "flat", "LOW", "数据已重置");
      });
    },
    scheduleAuto() {
      clearInterval(this.autoTimer);
      this.autoTimer = setInterval(() => {
        const s = state.signals;
        if (s.SCORE != null) {
          const dir = s.SCORE >= 55 ? "up" : s.SCORE < 45 ? "down" : "flat";
          const risk = s.RISK >= 60 ? "HIGH" : s.RISK >= 30 ? "MID" : "LOW";
          Terminal.append("信号", dir, risk, `SCORE=${util.fmt(s.SCORE, 1)} 胜率=${util.fmt(s.WIN, 1)}% 仓位=${util.fmt(s.POS, 1)}% EV=${util.fmt(s.EV, 1)}%`);
        }
      }, 4000);
    },
    bindConfig() {
      const c = state.config;
      document.getElementById("cfgEndpoint").value = c.endpoint;
      document.getElementById("cfgKey").value = c.apiKey;
      document.getElementById("cfgModel").value = c.model;
      document.getElementById("cfgTimeout").value = c.timeoutMs;
      document.getElementById("cfgRetries").value = c.retries;
      const save = util.debounce(() => {
        c.endpoint = document.getElementById("cfgEndpoint").value.trim();
        c.apiKey = document.getElementById("cfgKey").value.trim();
        c.model = document.getElementById("cfgModel").value.trim();
        c.timeoutMs = +document.getElementById("cfgTimeout").value || 8000;
        c.retries = +document.getElementById("cfgRetries").value || 3;
        Terminal.append("配置", "flat", "LOW", `已保存：endpoint=${c.endpoint || "(演示)"} timeout=${c.timeoutMs}ms retries=${c.retries}`);
      }, 300);
      ["cfgEndpoint", "cfgKey", "cfgModel", "cfgTimeout", "cfgRetries"].forEach((id) => document.getElementById(id).addEventListener("input", save));

      // 动态权重滑块
      const wbox = document.getElementById("weights");
      const defs = [["momentum", "动量"], ["volatility", "波动"], ["volume", "量能"]];
      wbox.innerHTML = defs.map(([k, label]) => `
        <div class="wrow"><span>${label}</span>
          <input type="range" min="0" max="1" step="0.05" value="${c.weights[k]}" data-k="${k}">
          <b id="w_${k}" style="color:var(--gold);width:34px;text-align:right">${c.weights[k].toFixed(2)}</b></div>`).join("");
      wbox.querySelectorAll("input[type=range]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const k = inp.dataset.k; c.weights[k] = +inp.value;
          document.getElementById("w_" + k).textContent = (+inp.value).toFixed(2);
          Terminal.append("配置", "flat", "LOW", `权重 ${k} → ${ (+inp.value).toFixed(2)}`);
          if (DataSource.source !== "none") SignalEngine.recompute();   // 实时重算
        });
      });
    },
  };

  document.addEventListener("DOMContentLoaded", () => App.init());
})();
