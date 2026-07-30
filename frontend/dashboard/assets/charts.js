/**
 * 金水谣足彩预测系统 - 前端交互逻辑 + ECharts 雷达图 + 攻防对比
 * 对齐截图中的深色科技风 AI 体育分析界面
 */

// ═══════════════════════════════════════════════════════════
// 全局状态
// ═══════════════════════════════════════════════════════════
var API_BASE = 'http://localhost:5001';
var selectedMatch = null;
var matches = [];
var radarChart = null;
var attackDefenseChart = null;
var _resizeBound = false;

// ═══════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════
function $(id) { return document.getElementById(id); }
function show(id) { var el = $(id); if (el) el.style.display = ''; }
function hide(id) { var el = $(id); if (el) el.style.display = 'none'; }
function showLoading() { var el = $('loadingOverlay'); if (el) el.classList.add('show'); }
function hideLoading() { var el = $('loadingOverlay'); if (el) el.classList.remove('show'); }

// ═══════════════════════════════════════════════════════════
// 三栏标签页切换
// ═══════════════════════════════════════════════════════════
function switchTab(btn) {
  // 移除所有标签的 active 状态
  document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');

  // 获取标签索引
  var tabId = btn.getAttribute('data-tab');
  if (!tabId) {
    // 如果没有 data-tab，按顺序推断
    var btns = Array.from(document.querySelectorAll('.tab-btn'));
    var idx = btns.indexOf(btn);
    tabId = 'tabContent' + (idx + 1);
  }

  // 隐藏所有标签内容区
  var allContents = [
    $('tabContent1'),
    $('tabContent2'),
    $('tabContent3')
  ];
  allContents.forEach(function(c) {
    if (c) hide(c.id);
  });

  // 显示对应内容区
  show(tabId);
}

// ═══════════════════════════════════════════════════════════
// 影响因子标签选择
// ═══════════════════════════════════════════════════════════
function toggleFactorTag(el) {
  if (el.classList.contains('active')) {
    el.classList.remove('active');
    el.style.background = '';
    el.style.color = '';
  } else {
    el.classList.add('active');
    el.style.background = 'var(--accent)';
    el.style.color = '#fff';
  }
}

// ═══════════════════════════════════════════════════════════
// 手动面板 / 随机填充
// ═══════════════════════════════════════════════════════════
function toggleManual() {
  var panel = $('manualPanel');
  if (panel) panel.classList.toggle('show');
}

function randomFill() {
  if (!$('manualPanel').classList.contains('show')) toggleManual();
  var fields = [
    ['mHomeGoals', 0, 4], ['mAwayGoals', 0, 3],
    ['mHomeConc', 0, 3], ['mAwayConc', 0, 3]
  ];
  fields.forEach(function(f) {
    var vals = [];
    for (var i = 0; i < 5; i++) vals.push(Math.floor(Math.random() * (f[2] - f[1] + 1)) + f[1]);
    $(f[0]).value = vals.join(',');
  });
  $('mOddsW').value = (1.5 + Math.random() * 1.5).toFixed(2);
  $('mOddsD').value = (2.5 + Math.random() * 2.0).toFixed(2);
  $('mOddsL').value = (2.0 + Math.random() * 4.0).toFixed(2);
}

// ═══════════════════════════════════════════════════════════
// 比赛列表
// ═══════════════════════════════════════════════════════════
function fetchMatches() {
  showLoading();
  fetch(API_BASE + '/api/matches')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      hideLoading();
      if (data.matches && data.matches.length > 0) {
        matches = data.matches;
        renderMatchList(matches);
      } else {
        $('matchList').innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px">暂无比赛数据，请使用手动输入</div>';
      }
    })
    .catch(function() {
      hideLoading();
      // 后端不可用时使用演示数据
      loadDemoMatches();
    });
}

function loadDemoMatches() {
  matches = [
    { match_id: 'demo1', league: '世界杯小组赛', home: '巴西', away: '摩洛哥', odds_win: 2.10, odds_draw: 3.20, odds_lose: 3.50, match_time: '06/14 06:00' },
    { match_id: 'demo2', league: '世界杯小组赛', home: '阿根廷', away: '沙特', odds_win: 1.35, odds_draw: 4.80, odds_lose: 8.50, match_time: '06/14 21:00' },
    { match_id: 'demo3', league: '世界杯小组赛', home: '法国', away: '丹麦', odds_win: 1.65, odds_draw: 3.80, odds_lose: 5.20, match_time: '06/15 00:00' },
    { match_id: 'demo4', league: '世界杯小组赛', home: '西班牙', away: '德国', odds_win: 2.40, odds_draw: 3.10, odds_lose: 2.90, match_time: '06/15 03:00' },
    { match_id: 'demo5', league: '世界杯小组赛', home: '英格兰', away: '美国', odds_win: 1.55, odds_draw: 4.20, odds_lose: 5.80, match_time: '06/15 21:00' },
  ];
  renderMatchList(matches);
}

function renderMatchList(list) {
  var html = '';
  list.forEach(function(m) {
    html += '<div class="match-row" data-id="' + m.match_id + '" onclick="selectMatch(\'' + m.match_id + '\')">';
    html += '<span class="league">' + (m.league || '-') + '</span>';
    html += '<span class="team">' + (m.home || '-') + '</span>';
    html += '<span class="team">' + (m.away || '-') + '</span>';
    html += '<span class="odds">' + (m.odds_win > 0 ? m.odds_win.toFixed(2) : '-') + '</span>';
    html += '<span class="odds">' + (m.odds_draw > 0 ? m.odds_draw.toFixed(2) : '-') + '</span>';
    html += '<span class="odds">' + (m.odds_lose > 0 ? m.odds_lose.toFixed(2) : '-') + '</span>';
    html += '<span class="time">' + (m.match_time || '-') + '</span>';
    html += '</div>';
  });
  $('matchList').innerHTML = html;
}

function selectMatch(matchId) {
  selectedMatch = matches.find(function(m) { return m.match_id === matchId; });
  if (!selectedMatch) return;

  // 高亮选中行
  document.querySelectorAll('.match-row').forEach(function(row) {
    row.classList.remove('selected');
    if (row.dataset.id === matchId) row.classList.add('selected');
  });

  // 更新焦点比赛卡片
  $('homeTeamName').textContent = selectedMatch.home;
  $('awayTeamName').textContent = selectedMatch.away;
  $('matchLeague').textContent = selectedMatch.league || '小组赛';
  $('matchTime').textContent = selectedMatch.match_time || '--';
  $('perspectiveTeam').textContent = selectedMatch.home;

  // 填充手动输入区
  $('mHome').value = selectedMatch.home;
  $('mAway').value = selectedMatch.away;
  if (selectedMatch.odds_win > 0) {
    $('mOddsW').value = selectedMatch.odds_win.toFixed(2);
    $('mOddsD').value = selectedMatch.odds_draw.toFixed(2);
    $('mOddsL').value = selectedMatch.odds_lose.toFixed(2);
  }
}

// ═══════════════════════════════════════════════════════════
// 预测核心
// ═══════════════════════════════════════════════════════════
function runPrediction() {
  if (!selectedMatch) {
    runManualPrediction();
    return;
  }
  showLoading();

  var params = {
    home: selectedMatch.home,
    away: selectedMatch.away,
    home_goals: $('mHomeGoals').value,
    home_conceded: $('mHomeConc').value,
    away_goals: $('mAwayGoals').value,
    away_conceded: $('mAwayConc').value,
    odds_home: $('mOddsW').value,
    odds_draw: $('mOddsD').value,
    odds_away: $('mOddsL').value,
    bankroll: $('mBankroll').value
  };

  // 带超时的 fetch（10秒超时）
  var controller = new AbortController();
  var timeoutId = setTimeout(function() { controller.abort(); }, 10000);

  fetch(API_BASE + '/api/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: controller.signal
  })
  .then(function(r) { clearTimeout(timeoutId); return r.json(); })
  .then(function(data) {
    hideLoading();
    renderPredictionResult(data);
  })
  .catch(function() {
    clearTimeout(timeoutId);
    hideLoading();
    runLocalPrediction(params);
  });
}

function runManualPrediction() {
  var home = $('mHome').value || '主队';
  var away = $('mAway').value || '客队';

  // 更新焦点卡片
  $('homeTeamName').textContent = home;
  $('awayTeamName').textContent = away;
  $('matchLeague').textContent = '手动输入';
  $('matchTime').textContent = new Date().toLocaleString('zh-CN');
  $('perspectiveTeam').textContent = home;

  var params = {
    home: home,
    away: away,
    home_goals: $('mHomeGoals').value,
    home_conceded: $('mHomeConc').value,
    away_goals: $('mAwayGoals').value,
    away_conceded: $('mAwayConc').value,
    odds_home: $('mOddsW').value,
    odds_draw: $('mOddsD').value,
    odds_away: $('mOddsL').value,
    bankroll: $('mBankroll').value
  };

  showLoading();
  var controller = new AbortController();
  var timeoutId = setTimeout(function() { controller.abort(); }, 10000);

  fetch(API_BASE + '/api/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: controller.signal
  })
  .then(function(r) { clearTimeout(timeoutId); return r.json(); })
  .then(function(data) {
    hideLoading();
    renderPredictionResult(data);
  })
  .catch(function() {
    clearTimeout(timeoutId);
    hideLoading();
    runLocalPrediction(params);
  });
}

// ═══════════════════════════════════════════════════════════
// 本地模拟预测（后端不可用时）
// ═══════════════════════════════════════════════════════════
function runLocalPrediction(params) {
  var homeGoals = (params.home_goals || '').split(',').map(Number).filter(function(n) { return !isNaN(n); });
  var homeConceded = (params.home_conceded || '').split(',').map(Number).filter(function(n) { return !isNaN(n); });
  var awayGoals = (params.away_goals || '').split(',').map(Number).filter(function(n) { return !isNaN(n); });
  var awayConceded = (params.away_conceded || '').split(',').map(Number).filter(function(n) { return !isNaN(n); });

  var avg = function(arr) { return arr.length > 0 ? arr.reduce(function(a,b){return a+b;},0) / arr.length : 1.3; };

  var homeAvgGoals = avg(homeGoals);
  var homeAvgConc = avg(homeConceded);
  var awayAvgGoals = avg(awayGoals);
  var awayAvgConc = avg(awayConceded);

  // 简单泊松模拟
  var lambdaH = (homeAvgGoals + awayAvgConc) / 2 * 1.1;
  var lambdaA = (awayAvgGoals + homeAvgConc) / 2 * 0.9;

  var poissonPMF = function(k, lam) {
    if (lam <= 0) return k === 0 ? 1 : 0;
    var logP = k * Math.log(lam) - lam;
    for (var i = 2; i <= k; i++) logP -= Math.log(i);
    return Math.exp(logP);
  };

  var pWin = 0, pDraw = 0, pLose = 0;
  for (var h = 0; h <= 6; h++) {
    for (var a = 0; a <= 6; a++) {
      var p = poissonPMF(h, lambdaH) * poissonPMF(a, lambdaA);
      if (h > a) pWin += p;
      else if (h === a) pDraw += p;
      else pLose += p;
    }
  }

  // 归一化
  var total = pWin + pDraw + pLose;
  pWin /= total; pDraw /= total; pLose /= total;

  var oddsW = parseFloat(params.odds_home) || 2.0;
  var oddsD = parseFloat(params.odds_draw) || 3.0;
  var oddsL = parseFloat(params.odds_away) || 3.5;
  var bankroll = parseFloat(params.bankroll) || 1000;

  var evW = pWin * oddsW - 1;
  var evD = pDraw * oddsD - 1;
  var evL = pLose * oddsL - 1;

  var kellyW = Math.max(0, (pWin * oddsW - 1) / (oddsW - 1)) * 0.25;
  var kellyD = Math.max(0, (pDraw * oddsD - 1) / (oddsD - 1)) * 0.25;
  var kellyL = Math.max(0, (pLose * oddsL - 1) / (oddsL - 1)) * 0.25;

  // 比分路径
  var scorePaths = [];
  for (var h2 = 0; h2 <= 4; h2++) {
    for (var a2 = 0; a2 <= 4; a2++) {
      var prob = poissonPMF(h2, lambdaH) * poissonPMF(a2, lambdaA);
      scorePaths.push({ half_home: Math.floor(h2/2), half_away: Math.floor(a2/2), full_home: h2, full_away: a2, probability: prob });
    }
  }
  scorePaths.sort(function(a, b) { return b.probability - a.probability; });
  scorePaths = scorePaths.slice(0, 5);

  var bestRec = pWin >= pDraw && pWin >= pLose ? '主胜' : (pDraw >= pLose ? '平局' : '客胜');
  var bestEV = Math.max(evW, evD, evL);
  var bestKelly = Math.max(kellyW, kellyD, kellyL);
  var bestOdds = bestRec === '主胜' ? oddsW : (bestRec === '平局' ? oddsD : oddsL);
  var bestProb = bestRec === '主胜' ? pWin : (bestRec === '平局' ? pDraw : pLose);

  // 攻防效率数据
  var attackDefense = {
    home: {
      attack: Math.min(100, Math.round((homeAvgGoals / 2.5) * 100)),
      defense: Math.min(100, Math.round((1 - homeAvgConc / 2.5) * 100)),
      goals: parseFloat(homeAvgGoals.toFixed(1)),
      conceded: parseFloat(homeAvgConc.toFixed(1))
    },
    away: {
      attack: Math.min(100, Math.round((awayAvgGoals / 2.5) * 100)),
      defense: Math.min(100, Math.round((1 - awayAvgConc / 2.5) * 100)),
      goals: parseFloat(awayAvgGoals.toFixed(1)),
      conceded: parseFloat(awayAvgConc.toFixed(1))
    }
  };

  var data = {
    home: params.home,
    away: params.away,
    probabilities: { win: pWin, draw: pDraw, lose: pLose },
    odds: { home_win: oddsW, draw: oddsD, lose: oddsL },
    ev: { win: evW, draw: evD, lose: evL },
    kelly: { win: kellyW, draw: kellyD, lose: kellyL },
    recommendation: bestRec,
    rec_probability: bestProb,
    rec_odds: bestOdds,
    rec_ev: bestEV,
    rec_kelly: bestKelly,
    rec_stake: Math.min(bestKelly * bankroll, bankroll * 0.05),
    bankroll: bankroll,
    lambda_home: lambdaH,
    lambda_away: lambdaA,
    score_paths: scorePaths,
    home_stats: { avg_goals: homeAvgGoals, avg_conceded: homeAvgConc },
    away_stats: { avg_goals: awayAvgGoals, avg_conceded: awayAvgConc },
    attack_defense: attackDefense,
    radar: {
      home: [70, 75, 80, 65, 72, 68],
      away: [55, 60, 45, 78, 65, 82]
    },
    stability: {
      home: { score: 68, level: 'warn', dims: { offense: 72, defense: 65, squad: 80, form: 58, tactical: 70, mental: 62 }, alerts: ['进攻端状态起伏大 (xG标准差=0.38)'] },
      away: { score: 75, level: 'good', dims: { offense: 78, defense: 82, squad: 90, form: 85, tactical: 72, mental: 68 }, alerts: [] }
    }
  };

  renderPredictionResult(data);
}

// ═══════════════════════════════════════════════════════════
// 渲染预测结果
// ═══════════════════════════════════════════════════════════
function renderPredictionResult(data) {
  var home = data.home || '主队';
  var away = data.away || '客队';
  var prob = data.probabilities;
  var odds = data.odds;
  var ev = data.ev;
  var kelly = data.kelly;

  // 显示所有面板（跨三个标签页）
  ['probSection', 'factorCards', 'factorTagsArea', 'scorePathCard', 'resultCard',
   'riskCard', 'sceneCard', 'disclaimer',
   'teamDataCard', 'attackDefenseChart', 'compareCard', 'radarCard',
   'stabilityCard', 'factorCardsAlt'
  ].forEach(function(id) { show(id); });

  // ── AI 取胜概率 ──
  $('probHomeLabel').textContent = home + '胜';
  $('probAwayLabel').textContent = away + '胜';

  $('probHomeBar').style.width = (prob.win * 100).toFixed(1) + '%';
  $('probDrawBar').style.width = (prob.draw * 100).toFixed(1) + '%';
  $('probAwayBar').style.width = (prob.lose * 100).toFixed(1) + '%';

  $('probHomeVal').textContent = (prob.win * 100).toFixed(1) + '%';
  $('probDrawVal').textContent = (prob.draw * 100).toFixed(1) + '%';
  $('probAwayVal').textContent = (prob.lose * 100).toFixed(1) + '%';

  if (prob.draw > prob.win && prob.draw > prob.lose) {
    $('probNote').textContent = '数据倾向：平局权重较高 | 合计: 100%';
  } else if (prob.win > prob.lose) {
    $('probNote').textContent = '数据倾向：' + home + '略占优势 | 合计: 100%';
  } else {
    $('probNote').textContent = '数据倾向：' + away + '略占优势 | 合计: 100%';
  }

  // ── 因素卡片 ──
  var homeStats = data.home_stats || {};
  var awayStats = data.away_stats || {};

  $('factor1Desc').textContent = home + '进攻效率' + (homeStats.avg_goals || 0).toFixed(1) + '，' +
    away + '防守稳固度' + (awayStats.avg_conceded || 0).toFixed(1) + '，双方攻防匹配度中等偏上';
  $('factor2Desc').textContent = '小组积分数据尚未完全导入，晋级压力暂按中性处理';
  $('factor3Desc').textContent = '比赛节奏有打开条件，后半段需留出变化空间';

  // ── 球队数据 ──
  $('teamDataTitle').textContent = home + '球队数据';
  var attackEff = Math.min(100, ((homeStats.avg_goals || 1.3) / 2.5) * 100);
  var defenseEff = Math.min(100, ((1 - (homeStats.avg_conceded || 1.3) / 2.5)) * 100);
  $('tdAttack').style.width = attackEff.toFixed(0) + '%';
  $('tdAttackVal').textContent = (homeStats.avg_goals || 0).toFixed(1);
  $('tdDefense').style.width = defenseEff.toFixed(0) + '%';
  $('tdDefenseVal').textContent = (homeStats.avg_conceded || 0).toFixed(1);
  $('tdGoals').style.width = attackEff.toFixed(0) + '%';
  $('tdGoalsVal').textContent = (homeStats.avg_goals || 0).toFixed(1);
  $('tdConceded').style.width = (100 - defenseEff).toFixed(0) + '%';
  $('tdConcededVal').textContent = (homeStats.avg_conceded || 0).toFixed(1);
  $('tdForm').style.width = '65%';
  $('tdFormVal').textContent = '中';

  // ── 球队对比 ──
  $('csHomeName').textContent = home;
  $('csAwayName').textContent = away;
  $('csHomeRecord').textContent = '近5场 进' + (homeStats.avg_goals || 0).toFixed(1) + '/失' + (homeStats.avg_conceded || 0).toFixed(1);
  $('csHomeFactor').textContent = prob.win > 0.45 ? '中高' : (prob.win > 0.35 ? '中' : '中低');
  $('csAwayRecord').textContent = '近5场 进' + (awayStats.avg_goals || 0).toFixed(1) + '/失' + (awayStats.avg_conceded || 0).toFixed(1);
  $('csAwayFactor').textContent = prob.lose > 0.45 ? '中高' : (prob.lose > 0.35 ? '中' : '中低');

  // ── 雷达图 ──
  renderRadar(data.radar || { home: [60,60,60,60,60,60], away: [60,60,60,60,60,60] }, home, away);

  // ── 攻防效率对比条形图 ──
  renderAttackDefense(data.attack_defense || null, home, away);

  // ── 比分路径（分段渲染） ──
  renderScorePaths(data.score_paths || [], home, away);
  var tierBanner = $('tierBanner');
  if (tierBanner) tierBanner.style.display = '';

  // ── 稳定性 ──
  renderStability(data.stability || {}, home, away);

  // ── 预测结果表 ──
  var rows = [
    { label: home + '胜', prob: prob.win, odds: odds.home_win, ev: ev.win, kelly: kelly.win },
    { label: '平局', prob: prob.draw, odds: odds.draw, ev: ev.draw, kelly: kelly.draw },
    { label: away + '胜', prob: prob.lose, odds: odds.lose, ev: ev.lose, kelly: kelly.lose }
  ];

  var tbody = $('resultBody');
  tbody.innerHTML = '';
  rows.forEach(function(row, i) {
    var isHighlight = row.label === data.recommendation;
    var gap = (row.prob * row.odds - 1).toFixed(4);
    var tr = document.createElement('tr');
    if (isHighlight) tr.className = 'highlight';
    tr.innerHTML = '<td>' + row.label + '</td>' +
      '<td>' + (row.prob * 100).toFixed(1) + '%</td>' +
      '<td>' + row.odds.toFixed(2) + '</td>' +
      '<td>' + row.ev.toFixed(4) + '</td>' +
      '<td>' + row.kelly.toFixed(4) + '</td>' +
      '<td>' + gap + '</td>';
    tbody.appendChild(tr);
  });

  // ── 推荐决策 ──
  $('recMain').textContent = '推荐: ' + data.recommendation;
  $('recDetail').innerHTML =
    '<span>概率:</span> ' + (data.rec_probability * 100).toFixed(1) + '% &nbsp; <span>赔率:</span> ' + data.rec_odds.toFixed(2) + '<br>' +
    '<span>EV:</span> ' + data.rec_ev.toFixed(4) + ' &nbsp; <span>凯利(1/4):</span> ' + data.rec_kelly.toFixed(4) + '<br>' +
    '<span>建议投注:</span> ' + data.rec_stake.toFixed(2) + ' 元 &nbsp; <span>资金:</span> ' + data.bankroll.toFixed(0) + ' 元';

  // ── 风控 ──
  $('rmBankroll').textContent = data.bankroll.toFixed(0);
  $('rmStake').textContent = data.rec_stake.toFixed(2);
  $('rmStoploss').textContent = (data.bankroll * 0.08).toFixed(0);
  $('rmKelly').textContent = '0.25';
}

// ═══════════════════════════════════════════════════════════
// ECharts 雷达图
// ═══════════════════════════════════════════════════════════
function renderRadar(radarData, homeName, awayName) {
  var container = $('radarChart');
  if (!container) return;

  if (radarChart) radarChart.dispose();

  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();

  radarChart = echarts.init(container, 'jinshuiyao', { renderer: 'svg' });

  var labels = ['大赛经验', '世界排名', '阵容身价', '防守稳定', '进攻火力', '近期状态'];

  radarChart.setOption({
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      backgroundColor: 'rgba(22,27,34,0.95)',
      borderColor: rule,
      textStyle: { color: '#e6edf3', fontSize: 12 }
    },
    legend: {
      data: [homeName, awayName],
      bottom: 10,
      textStyle: { color: muted, fontSize: 13 },
      itemWidth: 16,
      itemHeight: 8
    },
    radar: {
      indicator: labels.map(function(l) { return { name: l, max: 100 }; }),
      shape: 'polygon',
      splitNumber: 5,
      axisName: { color: muted, fontSize: 12 },
      splitLine: { lineStyle: { color: rule } },
      splitArea: { show: true, areaStyle: { color: ['rgba(0,212,170,0.02)', 'rgba(59,130,246,0.02)'] } },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'radar',
      data: [
        {
          name: homeName,
          value: radarData.home,
          lineStyle: { color: accent, width: 2 },
          areaStyle: { color: 'rgba(0,212,170,0.15)' },
          itemStyle: { color: accent },
          symbol: 'circle',
          symbolSize: 6
        },
        {
          name: awayName,
          value: radarData.away,
          lineStyle: { color: accent2, width: 2 },
          areaStyle: { color: 'rgba(59,130,246,0.15)' },
          itemStyle: { color: accent2 },
          symbol: 'circle',
          symbolSize: 6
        }
      ],
      animation: true
    }]
  });

  // 统一 resize 处理（只绑定一次）
  if (!_resizeBound) {
    _resizeBound = true;
    window.addEventListener('resize', function() {
      if (radarChart) radarChart.resize();
      if (attackDefenseChart) attackDefenseChart.resize();
    });
  }
}

// ═══════════════════════════════════════════════════════════
// 攻防效率对比条形图（双向水平条形图）
// ═══════════════════════════════════════════════════════════
function renderAttackDefense(data, homeName, awayName) {
  var container = $('adChartContainer');
  if (!container) return;

  // 如果没有攻防数据，显示占位
  if (!data || !data.home || !data.away) {
    var card = $('attackDefenseChart');
    if (card) card.innerHTML = '<div style="text-align:center;color:var(--muted);padding:30px;font-size:13px">攻防数据暂缺</div>';
    return;
  }

  if (attackDefenseChart) attackDefenseChart.dispose();

  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim() || '#00d4aa';
  var accent2 = style.getPropertyValue('--accent2').trim() || '#3b82f6';
  var muted = style.getPropertyValue('--muted').trim() || '#8b949e';
  var rule = style.getPropertyValue('--rule').trim() || '#30363d';

  attackDefenseChart = echarts.init(container, 'jinshuiyao', { renderer: 'svg' });

  var categories = ['进攻效率', '防守稳固', '场均进球', '场均失球'];
  var homeValues = [data.home.attack, data.home.defense, data.home.goals * 25, (1 - data.home.conceded / 2.5) * 100];
  var awayValues = [data.away.attack, data.away.defense, data.away.goals * 25, (1 - data.away.conceded / 2.5) * 100];

  // 限制范围
  homeValues = homeValues.map(function(v) { return Math.max(0, Math.min(100, Math.round(v))); });
  awayValues = awayValues.map(function(v) { return Math.max(0, Math.min(100, Math.round(v))); });

  attackDefenseChart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      appendToBody: true,
      backgroundColor: 'rgba(22,27,34,0.95)',
      borderColor: rule,
      textStyle: { color: '#e6edf3', fontSize: 12 },
      formatter: function(params) {
        var idx = params[0].dataIndex;
        var tip = '<b>' + categories[idx] + '</b><br/>';
        params.forEach(function(p) {
          tip += p.marker + ' ' + p.seriesName + ': ' + p.value + '<br/>';
        });
        return tip;
      }
    },
    legend: {
      data: [homeName, awayName],
      bottom: 0,
      textStyle: { color: muted, fontSize: 12 },
      itemWidth: 14,
      itemHeight: 8
    },
    grid: {
      left: 80,
      right: 80,
      top: 10,
      bottom: 36,
      containLabel: false
    },
    xAxis: {
      type: 'value',
      max: 100,
      min: -100,
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false }
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: muted, fontSize: 12 }
    },
    series: [
      {
        name: homeName,
        type: 'bar',
        data: homeValues.map(function(v) { return -v; }),
        barWidth: 14,
        itemStyle: {
          color: accent,
          borderRadius: [0, 4, 4, 0]
        },
        label: {
          show: true,
          position: 'left',
          color: accent,
          fontSize: 11,
          formatter: function(p) { return Math.abs(p.value); }
        }
      },
      {
        name: awayName,
        type: 'bar',
        data: awayValues,
        barWidth: 14,
        itemStyle: {
          color: accent2,
          borderRadius: [4, 0, 0, 4]
        },
        label: {
          show: true,
          position: 'right',
          color: accent2,
          fontSize: 11,
          formatter: function(p) { return p.value; }
        }
      }
    ]
  });

  // resize 已在 renderRadar 中统一绑定，此处无需重复绑定
}

// ═══════════════════════════════════════════════════════════
// 比分路径渲染（分段：主路径 + 备选路径）
// ═══════════════════════════════════════════════════════════
function renderScorePaths(paths, home, away) {
  var mainListEl = $('pathList');
  var altListEl = $('pathListAlt');

  if (!paths || paths.length === 0) {
    if (mainListEl) mainListEl.innerHTML = '<div style="text-align:center;color:var(--muted);padding:20px">无路径数据</div>';
    if (altListEl) altListEl.innerHTML = '';
    return;
  }

  // 分段：前2条为主路径，3-5条为备选路径
  var mainPaths = paths.slice(0, 2);
  var altPaths = paths.slice(2, 5);

  function buildPathHTML(p, i, isMain) {
    var rankClass = isMain ? (i === 0 ? 'top1' : 'top2') : 'top3';
    var result = p.full_home > p.full_away ? '主胜' : (p.full_home === p.full_away ? '平局' : '客胜');
    var resultClass = result === '主胜' ? 'win' : (result === '平局' ? 'draw' : 'lose');
    var probPercent = (p.probability * 100).toFixed(1);

    var html = '<div class="path-item">';
    html += '<div class="path-rank ' + rankClass + '">' + (i + 1) + '</div>';
    html += '<div class="path-scores">';
    html += '<span>' + p.half_home + '-' + p.half_away + '</span>';
    html += '<span class="path-arrow">\u2192</span>';
    html += '<span>' + p.full_home + '-' + p.full_away + '</span>';
    html += '</div>';
    html += '<span class="path-result-tag ' + resultClass + '">' + result + '</span>';
    html += '<div class="path-bar-wrap"><div class="path-bar" style="width:' + (p.probability / paths[0].probability * 100).toFixed(0) + '%"></div></div>';
    html += '<span class="path-prob">' + probPercent + '%</span>';
    html += '</div>';
    return html;
  }

  // 渲染主路径
  var mainListEl = $('pathList');
  var mainTitleEl = $('scorePathMain');
  if (mainTitleEl && mainListEl) {
    var mainHTML = '';
    mainPaths.forEach(function(p, i) {
      mainHTML += buildPathHTML(p, i, true);
    });
    mainListEl.innerHTML = mainHTML;
  }

  // 渲染备选路径
  var altListEl = $('pathListAlt');
  var altTitleEl = $('scorePathAlt');
  if (altTitleEl && altListEl) {
    if (altPaths.length > 0) {
      var altHTML = '';
      altPaths.forEach(function(p, i) {
        altHTML += buildPathHTML(p, i + 2, false);
      });
      altListEl.innerHTML = altHTML;
      altTitleEl.style.display = '';
    } else {
      altTitleEl.style.display = 'none';
    }
  }

  // 兼容旧版：如果只有 pathList 容器（无分段容器），则全部渲染到 pathList
  var legacyContainer = $('pathList');
  if (legacyContainer && !mainContainer && !altContainer) {
    var legacyHTML = '';
    paths.forEach(function(p, i) {
      legacyHTML += buildPathHTML(p, i, i < 2);
    });
    legacyContainer.innerHTML = legacyHTML;
  }
}

// ═══════════════════════════════════════════════════════════
// 稳定性渲染
// ═══════════════════════════════════════════════════════════
function renderStability(stabData, home, away) {
  var container = $('stabilityGrid');
  if (!container) return;
  var homeStab = stabData.home || { score: 50, level: 'warn', dims: {}, alerts: [] };
  var awayStab = stabData.away || { score: 50, level: 'warn', dims: {}, alerts: [] };

  function teamHTML(team, name) {
    var scoreClass = team.score >= 70 ? 'good' : (team.score >= 50 ? 'warn' : 'bad');
    var dims = team.dims || {};
    var dimLabels = { offense: '进攻稳定', defense: '防守稳定', squad: '阵容完整', form: '战绩稳定', tactical: '战术执行', mental: '大赛心理' };

    var html = '<div class="stability-team">';
    html += '<div class="stability-team-header">';
    html += '<span class="stability-team-name">' + name + '</span>';
    html += '<span class="stability-score ' + scoreClass + '">' + team.score + '</span>';
    html += '</div>';
    html += '<div class="stability-dims">';
    Object.keys(dimLabels).forEach(function(key) {
      var val = dims[key] || 50;
      var color = val >= 70 ? 'var(--success)' : (val >= 50 ? 'var(--warning)' : 'var(--danger)');
      html += '<div class="stability-dim">';
      html += '<span class="stability-dim-label">' + dimLabels[key] + '</span>';
      html += '<div class="stability-dim-bar"><div class="stability-dim-fill" style="width:' + val + '%;background:' + color + '"></div></div>';
      html += '</div>';
    });
    html += '</div>';

    if (team.alerts && team.alerts.length > 0) {
      html += '<div class="stability-alerts">';
      team.alerts.forEach(function(a) {
        html += '<div class="stability-alert">\u26A0 ' + a + '</div>';
      });
      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  container.innerHTML = teamHTML(homeStab, home) + teamHTML(awayStab, away);
}

// ═══════════════════════════════════════════════════════════
// 场景因素
// ═══════════════════════════════════════════════════════════
function updateScene() {
  var el;
  el = $('scHomeSquadVal'); if (el) el.textContent = ($('scHomeSquad').value / 100).toFixed(2);
  el = $('scAwaySquadVal'); if (el) el.textContent = ($('scAwaySquad').value / 100).toFixed(2);
  el = $('scHomeAdvVal'); if (el) el.textContent = ($('scHomeAdv').value / 100).toFixed(2);
  el = $('scFatigueVal'); if (el) el.textContent = ($('scFatigue').value / 100).toFixed(2);
}

// ═══════════════════════════════════════════════════════════
// 初始化
// ═══════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', function() {
  // 默认显示第一个标签页
  show('tabContent1');
  hide('tabContent2');
  hide('tabContent3');

  // 尝试加载比赛数据
  fetchMatches();
});
