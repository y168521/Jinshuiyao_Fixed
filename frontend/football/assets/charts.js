/* 金水谣足彩仪表盘 — 核心逻辑（对接真实 API） */
(function () {
  "use strict";

  var BASE = window.location.origin;
  var selectedMatch = null;

  /* ─── 赛程获取 ─── */
  window.fetchMatches = function () {
    var list = document.getElementById("matchList");
    if (!list) return;
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px">加载中...</div>';
    fetch(BASE + "/api/football/matches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 20 })
    })
    .then(function (r) { return r.json(); })
    .then(function (j) {
      if (!j.ok || !j.matches || !j.matches.length) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted)">暂无比赛数据</div>';
        return;
      }
      list.innerHTML = j.matches.map(function (m) {
        return '<div class="match-row" onclick="selectMatch(' +
          " '" + escAttr(m.home) + "','" + escAttr(m.away) + "','" + escAttr(m.league||'') + "','" + escAttr(m.date||'') + "'," +
          " '" + escAttr(m.home_odds||'') + "','" + escAttr(m.draw_odds||'') + "','" + escAttr(m.away_odds||'') + "'" +
          ' )">' +
          '<span class="league">' + esc(m.league||'') + '</span>' +
          '<span class="team">' + esc(m.home) + '</span>' +
          '<span class="team">' + esc(m.away) + '</span>' +
          '<span class="odds">' + esc(m.home_odds||'—') + '</span>' +
          '<span class="odds">' + esc(m.draw_odds||'—') + '</span>' +
          '<span class="odds">' + esc(m.away_odds||'—') + '</span>' +
          '<span class="time">' + esc(m.date||'') + '</span></div>';
      }).join("");
    })
    .catch(function () {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted)">加载失败</div>';
    });
  };

  function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
  function escAttr(s) { return String(s).replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }

  /* ─── 比赛选择 ─── */
  window.selectMatch = function (home, away, league, date, hOdds, dOdds, aOdds) {
    document.getElementById("homeTeamName").textContent = home;
    document.getElementById("awayTeamName").textContent = away;
    document.getElementById("matchLeague").textContent = league || "—";
    document.getElementById("matchTime").textContent = date || "—";
    document.getElementById("perspectiveTeam").textContent = home;
    // 同步到手动面板
    document.getElementById("mHome").value = home;
    document.getElementById("mAway").value = away;
    if (hOdds) document.getElementById("mOddsW").value = parseFloat(hOdds);
    if (dOdds) document.getElementById("mOddsD").value = parseFloat(dOdds);
    if (aOdds) document.getElementById("mOddsL").value = parseFloat(aOdds);
    selectedMatch = { home: home, away: away, league: league };
    // 高亮选中行
    document.querySelectorAll(".match-row").forEach(function (r) { r.classList.remove("selected"); });
    event && event.currentTarget && event.currentTarget.classList.add("selected");
  };

  /* ─── 预测（AI分析）─ ─── */
  window.runPrediction = function () {
    var home = document.getElementById("homeTeamName").textContent;
    var away = document.getElementById("awayTeamName").textContent;
    if (!home || home === "选择比赛") { alert("请先选择一场比赛"); return; }
    runAnalysis(home, away, parseInt(document.getElementById("mBankroll").value) || 1000);
  };

  window.runManualPrediction = function () {
    var home = document.getElementById("mHome").value.trim();
    var away = document.getElementById("mAway").value.trim();
    if (!home || !away) { alert("请输入主客队名称"); return; }
    runAnalysis(home, away, parseInt(document.getElementById("mBankroll").value) || 1000);
  };

  function runAnalysis(home, away, bankroll) {
    showLoading(true);
    document.getElementById("homeTeamName").textContent = home;
    document.getElementById("awayTeamName").textContent = away;

    fetch(BASE + "/api/football/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home: home, away: away, bankroll: bankroll })
    })
    .then(function (r) { return r.json(); })
    .then(function (j) {
      showLoading(false);
      if (!j.ok || !j.prediction) {
        alert("预测接口返回异常");
        return;
      }
      renderPrediction(j.prediction, home, away);
    })
    .catch(function (e) {
      showLoading(false);
      alert("预测请求失败: " + (e.message || e));
    });
  }

  function renderPrediction(p, home, away) {
    // 概率
    document.getElementById("probHomeLabel").textContent = home + " 胜";
    document.getElementById("probAwayLabel").textContent = away + " 胜";
    document.getElementById("probHomeVal").textContent = p.home_prob + "%";
    document.getElementById("probDrawVal").textContent = p.draw_prob + "%";
    document.getElementById("probAwayVal").textContent = p.away_prob + "%";
    document.getElementById("probHomeBar").style.width = p.home_prob + "%";
    document.getElementById("probDrawBar").style.width = p.draw_prob + "%";
    document.getElementById("probAwayBar").style.width = p.away_prob + "%";
    document.getElementById("probSection").style.display = "block";
    document.getElementById("probNote").textContent =
      "AI模拟基于泊松模型+市场赔率校准" +
      (p.expected_goals ? " · 预期进球 " + (p.expected_goals.home||'—') + ":" + (p.expected_goals.away||'—') : "") +
      (p.market_margin ? " · 庄家抽水 " + (p.market_margin*100).toFixed(1) + "%" : "");

    // 推荐
    document.getElementById("recMain").textContent = "推荐: " + (p.recommendation || "—");
    document.getElementById("recDetail").innerHTML =
      "信心: " + (p.confidence || "—") +
      (p.ev ? " · EV: " + (p.ev*100).toFixed(1) + "%" : "") +
      (p.suggested_stake ? " · 建议投注: " + p.suggested_stake + "元" : "");
    document.getElementById("recMainAlt").textContent = "推荐: " + (p.recommendation || "—");
    document.getElementById("recDetailAlt").textContent = "建议投注: " + (p.suggested_stake || "—") + "元";
    document.getElementById("resultCard").style.display = "block";
    document.getElementById("recCard").style.display = "block";
    document.getElementById("disclaimer").style.display = "block";

    // 风控
    document.getElementById("rmBankroll").textContent = (parseInt(document.getElementById("mBankroll").value) || 1000) + "元";
    document.getElementById("rmStake").textContent = (p.suggested_stake || "—") + "元";
    document.getElementById("rmKelly").textContent = p.tier || "—";
    document.getElementById("riskCard").style.display = "block";

    // 比分路径
    if (p.score_paths && p.score_paths.length) {
      var mainEl = document.getElementById("pathList");
      var altEl = document.getElementById("pathListAlt");
      var mainPaths = p.score_paths.slice(0, 3);
      var altPaths = p.score_paths.slice(3, 6);
      mainEl.innerHTML = mainPaths.map(function (sp, i) {
        var rankCls = i === 0 ? "top1" : i === 1 ? "top2" : "top3";
        var resultCls = sp.result === "主胜" ? "win" : sp.result === "客胜" ? "lose" : "draw";
        return '<div class="path-item"><span class="path-rank ' + rankCls + '">' + (i+1) + '</span>' +
          '<span class="path-scores">' + esc(sp.score) + '</span>' +
          (sp.result ? '<span class="path-result-tag ' + resultCls + '">' + esc(sp.result) + '</span>' : '') +
          '<div class="path-bar-wrap"><div class="path-bar" style="width:' + sp.prob + '%"></div></div>' +
          '<span class="path-prob">' + sp.prob + '%</span></div>';
      }).join("");
      altEl.innerHTML = altPaths.length
        ? altPaths.map(function (sp, i) {
            return '<div class="path-item"><span class="path-rank top3">' + (i+4) + '</span>' +
              '<span class="path-scores">' + esc(sp.score) + '</span>' +
              '<div class="path-bar-wrap"><div class="path-bar" style="width:' + sp.prob + '%"></div></div>' +
              '<span class="path-prob">' + sp.prob + '%</span></div>';
          }).join("")
        : '<div style="text-align:center;color:var(--muted);padding:12px;font-size:12px">更多路径</div>';
      document.getElementById("scorePathCard").style.display = "block";
    }

    // 结果表
    var tbody = document.getElementById("resultBody");
    tbody.innerHTML = "";
    var outcomes = [{ label: home + " 胜", prob: p.home_prob || 0, odds: "—", cls: "highlight" },
                    { label: "平局", prob: p.draw_prob || 0, odds: "—" },
                    { label: away + " 胜", prob: p.away_prob || 0, odds: "—" }];
    outcomes.forEach(function (o) {
      var tr = document.createElement("tr");
      if (o.cls) tr.className = o.cls;
      tr.innerHTML = "<td>" + esc(o.label) + "</td><td>" + o.prob + "%</td>" +
        "<td>" + o.odds + "</td><td>—</td><td>—</td><td>—</td>";
      tbody.appendChild(tr);
    });
  }

  /* ─── 场景调节 ─── */
  window.updateScene = function () {
    document.getElementById("scHomeSquadVal").textContent = (document.getElementById("scHomeSquad").value / 100).toFixed(2);
    document.getElementById("scAwaySquadVal").textContent = (document.getElementById("scAwaySquad").value / 100).toFixed(2);
    document.getElementById("scHomeAdvVal").textContent = (document.getElementById("scHomeAdv").value / 100).toFixed(2);
    document.getElementById("scFatigueVal").textContent = (document.getElementById("scFatigue").value / 100).toFixed(2);
  };

  window.toggleManual = function () {
    var p = document.getElementById("manualPanel");
    p.classList.toggle("show");
  };

  window.randomFill = function () {
    var teams = ["巴西","阿根廷","法国","英格兰","德国","西班牙","葡萄牙","荷兰","意大利","比利时"];
    var h = teams[Math.floor(Math.random() * teams.length)];
    var a = teams.filter(function (t) { return t !== h; })[Math.floor(Math.random() * (teams.length - 1))];
    document.getElementById("mHome").value = h;
    document.getElementById("mAway").value = a;
    document.getElementById("mOddsW").value = (1.2 + Math.random() * 4).toFixed(2);
    document.getElementById("mOddsD").value = (2.5 + Math.random() * 2).toFixed(2);
    document.getElementById("mOddsL").value = (1.2 + Math.random() * 4).toFixed(2);
    runManualPrediction();
  };

  function showLoading(show) {
    var el = document.getElementById("loadingOverlay");
    if (el) el.classList.toggle("show", show);
  }

  /* ─── 数据源诚实检测（W63补71 / 债务-108）─── */
  window.loadStatus = function () {
    var sysDot = document.getElementById("sysDot");
    var sysStatus = document.getElementById("sysStatus");
    var notice = document.getElementById("dataNotice");
    if (!notice) return;
    fetch(BASE + "/api/football/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    })
    .then(function (r) { return r.json(); })
    .then(function (j) {
      var st = j.status || {};
      var csvCount = parseInt(st.csv_count || 0, 10);
      var linkReal = '<a href="' + BASE + '/football/matches">比赛列表</a>';
      if (st.csv_data && csvCount > 0) {
        sysDot.style.background = "var(--success-bright)";
        sysStatus.textContent = "真实赛程数据 · " + csvCount + " 场";
        notice.className = "data-notice real";
        notice.innerHTML = "当前已接入真实赛程数据（" + csvCount + " 场），预测分析基于内置模型估算，" +
          "仅供研究参考，不构成任何投注建议。真实数据入口：" + linkReal + " | <a href='" + BASE + "/football/predict'>赛事预测</a>";
      } else {
        sysDot.style.background = "var(--warning)";
        sysStatus.textContent = "模拟演示模式（无真实赛程数据）";
        notice.className = "data-notice mock";
        notice.innerHTML = "⚠ 模拟演示模式：当前未检测到真实赛程数据（matches.csv 为空或缺失），" +
          "页面图表为演示示例，<b>不可用于任何真实决策</b>。真实数据处理页：" + linkReal + " | <a href='" + BASE + "/football/predict'>赛事预测</a>";
      }
    })
    .catch(function () {
      sysDot.style.background = "var(--danger)";
      sysStatus.textContent = "数据源检测失败";
      notice.className = "data-notice mock";
      notice.innerHTML = "⚠ 无法连接足彩数据服务，页面为静态演示示例，不可用于真实决策。";
    });
  };

  /* ─── 自动加载 ─── */
  document.addEventListener("DOMContentLoaded", function () {
    loadStatus();
    fetchMatches();
    updateScene();
  });

})();
