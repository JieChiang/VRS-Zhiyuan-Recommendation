const $ = (id) => document.getElementById(id);
const filters = {
  level: null,
  nature: null,
};
let drawerTrigger = null;
let detailRequestId = 0;

function parseMeta(raw) {
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  if (typeof raw === "string") {
    try { return JSON.parse(raw); } catch (_) { return {}; }
  }
  return {};
}

function getCompareList() {
  return getState(STORAGE_KEYS.compareList, []);
}

function setCompareList(items) {
  return setState(STORAGE_KEYS.compareList, items);
}

function toggleCompare(item) {
  const list = getCompareList();
  const key = `${item.institution}|${item.major}|${item.year}`;
  const idx = list.findIndex((x) => `${x.institution}|${x.major}|${x.year}` === key);
  if (idx >= 0) list.splice(idx, 1);
  else list.push(item);
  setCompareList(list);
  render();
}

async function removeRecommendItem(item) {
  try {
    await api("/api/v1/recycle/add", "POST", { bin_type: "S", item });
  } catch (err) {
    showToast("移除失败，推荐已保留：" + err.message, "error");
    return;
  }
  const result = getState(STORAGE_KEYS.recommendResult, {});
  const key = `${item.institution}|${item.major}|${item.year}`;
  ["all", "chong", "wen", "bao"].forEach((k) => {
    result[k] = (result[k] || []).filter((x) => `${x.institution}|${x.major}|${x.year}` !== key);
  });
  if (!setState(STORAGE_KEYS.recommendResult, result)) return;
  showToast("已移至回收站", "info", 2000);
  render();
}

function render() {
  const result = getState(STORAGE_KEYS.recommendResult, {});
  const all = result.all || [];
  const compareList = getCompareList();
  const counts = Object.fromEntries(["冲", "稳", "保"].map((layer) => [layer, all.filter((x) => x.layer === layer).length]));
  const meta = result.meta || {};
  const diagnostics = meta.filter_diagnostics || {};
  const explanation = [];
  if (meta.recommendation_version && meta.recommendation_version !== RECOMMENDATION_VERSION || (all.length && !meta.recommendation_version)) {
    explanation.push("当前为旧版筛选结果，请点击“按当前条件重新生成”。");
  }
  if (meta.rank_range) explanation.push(`${meta.reference_year} 年浙江历史参考 · 位次 ${meta.rank_range.join("–")} · 意向省份/城市：${(meta.requested_locations || []).join("、") || "不限"}。以位次检索，分数不作二次硬筛选。`);
  else if (meta.candidate_scope === "all") explanation.push(`${meta.reference_year} 年浙江历史参考 · 全部历史位次 · 意向省份/城市：${(meta.requested_locations || []).join("、") || "不限"}。${meta.subject_selection_complete ? "满足选科要求" : "可供探索"}的候选 ${diagnostics.primary_candidates ?? all.length} 条，按冲稳保展示 ${all.length} 条；分数不作二次硬筛选。`);
  explanation.push(...(meta.warnings || []));
  if (diagnostics.major_resolutions?.length) explanation.push("领域解释：" + diagnostics.major_resolutions.map((r) => `${r.input} → ${r.scope.join("、")}（${r.level}）`).join("；"));
  if (diagnostics.retrieved !== undefined) explanation.push(`初筛 ${diagnostics.retrieved} 条；排除仅方向文字相关 ${diagnostics.unrelated_direction_excluded} 条、选科明确不符 ${diagnostics.subject_excluded} 条；剩余 ${diagnostics.available_candidates} 条，其中 ${diagnostics.subject_unrestricted ?? 0} 条不限选科、${diagnostics.subject_pending} 条选科待核实。`);
  $("recommendDiagnostics").textContent = explanation.join("\n");
  $("recommendDiagnostics").classList.toggle("hidden", !explanation.length);
  const pending = result.pending_candidates || [];
  $("pendingCandidates").classList.toggle("hidden", !pending.length);
  $("pendingCandidatesTitle").textContent = `另有 ${pending.length} 条选科资料待核实的历史记录（不计入已核验推荐）`;
  $("pendingCandidatesList").textContent = pending.map((x) => `${x.institution} · ${x.major} · 历史位次 ${x.min_rank} · ${x.source_file} 第${x.source_row}行`).join("\n");
  $("recommendMeta").innerHTML = [[all.length, "当前候选"], [counts["冲"], "冲 · 积极尝试"], [counts["稳"], "稳 · 接近历史位次"], [counts["保"], "保 · 留有位次余量"]]
    .map(([n, label]) => `<div class="summary-tile"><b>${n}</b><span>${label}</span></div>`).join("");
  const list = $("recommendList");
  list.innerHTML = "";
  const keyword = $("recommendSearch").value.trim().toLowerCase();
  const layer = $("layerFilter").value;
  const filtered = all.filter((x) => {
    const level = String(x.level || "");
    const nature = String(x.school_nature || "");
    return (!filters.level || (filters.level === "college" ? level.includes("专科") : level.includes("本科"))) &&
      (!filters.nature || (filters.nature === "public" ? nature.includes("公办") : nature.includes("民办"))) &&
      (!layer || x.layer === layer) && (!keyword || `${x.institution} ${x.major}`.toLowerCase().includes(keyword));
  });
  $("recommendCount").textContent = `显示 ${filtered.length} / ${all.length} 条 · 已选对比 ${compareList.length} 条`;
  toggleEmptyState("recommendList", filtered.length === 0);
  const generated = !!meta.recommendation_version;
  $("recommendEmpty").querySelector(".empty-title").textContent = all.length ? "没有符合筛选条件的结果" : generated ? "当前条件下暂无推荐" : "暂无推荐结果";
  $("recommendEmpty").querySelector(".empty-description").textContent = all.length ? "可清除筛选条件后重试；属性未知的院校不会纳入对应筛选。" : generated ? "请查看上方筛选说明，可调整专业、地区、检索范围或冲稳保比例后重新生成。" : "请先在规划工作台填写信息并生成推荐。";
  $("recommendEmpty").querySelector(".empty-action").classList.toggle("hidden", all.length > 0);
  filtered.forEach((x) => {
    const key = `${x.institution}|${x.major}|${x.year}`;
    const selected = compareList.some((c) => `${c.institution}|${c.major}|${c.year}` === key);
    const layerClass = { "冲": "chong", "稳": "wen", "保": "bao" }[x.layer] || "unknown";
    let officialUrl = `https://www.baidu.com/s?wd=${encodeURIComponent(`${x.institution} 官网`)}`;
    try {
      const website = new URL(x.website);
      if (["http:", "https:"].includes(website.protocol)) officialUrl = website.href;
    } catch (_) {}
    const h = (value) => escapeHtml(String(value ?? "—"));
    const div = document.createElement("article");
    div.className = "list-item";
    div.innerHTML = `<div class="list-item-header"><span class="list-item-title">${h(x.institution)}</span><span class="layer-tag layer-${layerClass}">${h(x.layer || "未分层")}</span></div>
      <div>${h(x.major)}</div>
      <div class="recommend-tags"><span>${h(x.year)} 年参考数据</span>${getProbBadge(x.institution, x.major)}</div>
      <div class="recommend-stats"><div><b>${h(x.min_rank)}</b><small>历史最低位次</small></div><div><b>${h(x.min_score)}</b><small>历史最低分</small></div><div><b>${h(x.plan_count)}</b><small>历史计划数</small></div></div>
      <div class="recommend-tags"><span>${h(x.destination_city || x.destination_province || "所在地待核实")}</span><span>${h(subjectEligibilityLabel(x))}</span><span>${h(x.level || "层次待核实")}</span><span>${h(x.school_nature || "性质待核实")}</span><a href="${h(officialUrl)}" target="_blank" rel="noopener noreferrer">${x.website && officialUrl !== x.website ? "院校网站 / 搜索" : x.website ? "院校网站 ↗" : "搜索官网 ↗"}</a></div>
      <div class="list-item-actions"><button class="btn btn-sm ${selected ? "btn-secondary" : "btn-primary"} js-toggle" aria-pressed="${selected}">${selected ? "移出对比" : "加入对比"}</button><button class="btn btn-sm btn-secondary js-detail">查看详情</button><button class="btn btn-sm btn-ghost js-remove">移除</button></div>`;
    div.querySelector(".js-toggle").addEventListener("click", () => toggleCompare(x));
    div.querySelector(".js-detail").addEventListener("click", () => showDetail(x));
    div.querySelector(".js-remove").addEventListener("click", () => removeRecommendItem(x));
    list.appendChild(div);
  });
}

function renderRankingTable(rows) {
  if (!rows || !rows.length) return "<div>暂无</div>";
  const trs = rows
    .map((r) =>
      `<tr><td>${escapeHtml(String(r.list_type ?? "-"))} (${escapeHtml(String(r.year ?? "—"))})</td><td>${escapeHtml(String(r.rank ?? "-"))}</td><td>${escapeHtml(String(r.world_rank ?? "-"))}</td><td>${escapeHtml(String(r.score ?? "-"))}</td></tr>`)
    .join("");
  return `<table class="simple-table"><thead><tr><th>榜单</th><th>排名</th><th>世界排名</th><th>得分</th></tr></thead><tbody>${trs}</tbody></table>`;
}

function renderSubjectEvalTable(rows) {
  if (!rows || !rows.length) return "<div>暂无</div>";
  const trs = rows
    .map((r) => `<tr><td>${escapeHtml(String(r.subject_name ?? "-"))}</td><td>${escapeHtml(String(r.grade ?? "-"))}</td></tr>`)
    .join("");
  return `<table class="simple-table"><thead><tr><th>学科名称</th><th>评级</th></tr></thead><tbody>${trs}</tbody></table>`;
}

function drawTruncatedBar(domId, labels, values, title) {
  const dom = document.getElementById(domId);
  if (!dom) return;
  dom.textContent = "";
  if (!window.echarts) { dom.textContent = "图表组件加载失败，请检查网络后刷新"; return; }
  const existing = echarts.getInstanceByDom(dom);
  if (existing) existing.dispose();
  const valid = values.filter((v) => typeof v === "number" && !Number.isNaN(v));
  if (!valid.length) { dom.textContent = "暂无满意度数据"; return; }
  const chart = echarts.init(dom, getEChartsTheme());
  const minV = valid.length ? Math.min(...valid) : 0;
  const maxV = valid.length ? Math.max(...valid) : 5;
  const yMin = Math.max(0, Math.floor((minV - 0.2) * 10) / 10);
  const yMax = Math.min(5, Math.ceil((maxV + 0.1) * 10) / 10);
  chart.setOption({
    title: { text: title, left: "center", textStyle: { fontSize: 13, color: getComputedStyle(document.documentElement).getPropertyValue('--color-text-secondary').trim() || '#94a3b8' } },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: labels, axisLabel: { color: getComputedStyle(document.documentElement).getPropertyValue('--color-text-muted').trim() || '#94a3b8' } },
    yAxis: { type: "value", min: yMin, max: yMax, axisLabel: { color: getComputedStyle(document.documentElement).getPropertyValue('--color-text-muted').trim() || '#94a3b8' } },
    series: [{ type: "bar", data: values, barWidth: "45%", itemStyle: { color: "#1E40AF" }, emphasis: { itemStyle: { color: "#3B82F6" } } }],
    grid: { top: 40, left: 40, right: 10, bottom: 30 },
    backgroundColor: 'transparent',
  });
}

function drawEmploymentPie(rows) {
  const dom = document.getElementById("employmentChart");
  if (!dom) return;
  dom.textContent = "";
  if (!window.echarts) { dom.textContent = "图表组件加载失败，请检查网络后刷新"; return; }
  const existing = echarts.getInstanceByDom(dom);
  if (existing) existing.dispose();
  if (!rows.length) { dom.textContent = "暂无就业流向数据"; return; }
  const chart = echarts.init(dom, getEChartsTheme());
  chart.setOption({
    tooltip: { trigger: "item" },
    legend: { orient: "vertical", right: 0, top: "middle", textStyle: { color: getComputedStyle(document.documentElement).getPropertyValue('--color-text-secondary').trim() || '#b0bec5' } },
    series: [{
      type: "pie",
      radius: ["35%", "68%"],
      center: ["34%", "50%"],
      data: (rows || []).map((x) => ({ name: x.name, value: x.pct })),
      label: { formatter: "{b}: {d}%", color: getComputedStyle(document.documentElement).getPropertyValue('--color-text-secondary').trim() || '#b0bec5' },
    }],
    backgroundColor: 'transparent',
  });
}

async function showDetail(item) {
  const requestId = ++detailRequestId;
  drawerTrigger = document.activeElement;
  try {
    const drawer = document.getElementById("detailDrawer");
    const overlay = document.getElementById("drawerOverlay");
    drawer.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    $("closeDetailBtn").focus();
    ["detailRanking", "detailSubjectEval"].forEach((id) => $(id).textContent = "加载中…");
    ["instSatChart", "majorSatChart", "employmentChart"].forEach((id) => {
      if (window.echarts) window.echarts.getInstanceByDom($(id))?.dispose();
    });
    overlay.classList.remove("hidden");
    document.getElementById("detailTitle").textContent = `${item.institution} - ${item.major}`;
    document.getElementById("detailText").textContent = "正在加载详情...";
    const data = await api(
      `/api/v1/recommend/detail?institution=${encodeURIComponent(item.institution)}&major=${encodeURIComponent(item.major)}&year=${encodeURIComponent(item.year)}&fact_id=${encodeURIComponent(item.fact_id || "")}`
    );
    if (requestId !== detailRequestId) return;
    const base = data.base || {};
    document.getElementById("detailText").textContent =
      `院校层次：${data.level_text || "暂无"}\n最低分：${base.min_score ?? "-"}\n最低位次：${base.min_rank ?? "-"}\n计划数：${base.plan_count ?? "-"}\n选科要求：${base.subject_requirement_display || base.subject_requirement || "待核实"}\n数据来源：${base.source_file || "暂无"} / ${base.source_sheet || ""} / 第 ${base.source_row || "—"} 行\n计划来源：${base.plan_source || "未匹配到同年唯一计划"}\n生源：浙江`;
    document.getElementById("detailSubjectEval").innerHTML = renderSubjectEvalTable(data.subject_eval_items || []);
    document.getElementById("detailRanking").innerHTML = renderRankingTable(data.rankings || []);

    const iSat = data.institution_satisfaction || {};
    drawTruncatedBar("instSatChart", ["综合", "环境", "生活"],
      [iSat.overall, iSat.environment, iSat.life].map(chartNumber), "院校满意度");
    const mSat = data.major_satisfaction || {};
    drawTruncatedBar("majorSatChart", ["综合", "就业", "教学", "条件"],
      [mSat.overall, mSat.employment, mSat.teaching, mSat.condition].map(chartNumber), "专业满意度");
    drawEmploymentPie(data.employment_flow || []);
  } catch (err) {
    if (requestId !== detailRequestId) return;
    document.getElementById("detailText").textContent = `详情加载失败：${err.message || err}`;
    showToast("详情加载失败", "error");
  }
}

function closeDrawer() {
  detailRequestId++;
  document.body.style.overflow = "";
  drawerTrigger?.focus();
  document.getElementById("detailDrawer").classList.add("hidden");
  document.getElementById("drawerOverlay").classList.add("hidden");
}

function chartNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function bindFilterButtons() {
  const btnCollege = $("filterCollege");
  const btnBachelor = $("filterBachelor");
  const btnPublic = $("filterPublic");
  const btnPrivate = $("filterPrivate");

  const syncClass = () => {
    [[btnCollege, filters.level === "college"], [btnBachelor, filters.level === "bachelor"], [btnPublic, filters.nature === "public"], [btnPrivate, filters.nature === "private"]].forEach(([btn, selected]) => btn.setAttribute("aria-pressed", String(selected)));
    btnCollege.classList.toggle("btn-primary", filters.level === "college");
    btnBachelor.classList.toggle("btn-primary", filters.level === "bachelor");
    btnPublic.classList.toggle("btn-primary", filters.nature === "public");
    btnPrivate.classList.toggle("btn-primary", filters.nature === "private");
  };

  btnCollege.addEventListener("click", () => {
    filters.level = filters.level === "college" ? null : "college";
    syncClass(); render();
  });
  btnBachelor.addEventListener("click", () => {
    filters.level = filters.level === "bachelor" ? null : "bachelor";
    syncClass(); render();
  });
  btnPublic.addEventListener("click", () => {
    filters.nature = filters.nature === "public" ? null : "public";
    syncClass(); render();
  });
  btnPrivate.addEventListener("click", () => {
    filters.nature = filters.nature === "private" ? null : "private";
    syncClass(); render();
  });
  syncClass();
}

// ── Admission Probability ──
async function loadProbability() {
  const result = getState(STORAGE_KEYS.recommendResult, {});
  const all = result.all || [];
  if (!all.length) { showToast("没有推荐数据", "warning"); return; }

  const mainInput = getState(STORAGE_KEYS.mainInput, {});
  const rank = mainInput.rank || 0;
  const btn = $("loadProbabilityBtn");
  btn.disabled = true;
  btn.textContent = "计算中...";

  try {
    const batchSize = 20;
    let allProbs = {};
    for (let i = 0; i < all.length; i += batchSize) {
      const batch = all.slice(i, i + batchSize).map((x) => ({
        institution: x.institution,
        major: x.major,
      }));
      const data = await api("/api/v1/recommend/probability", "POST", {
        rank: rank,
        items: batch,
        year: all[0]?.year || 2024,
      });
      Object.assign(allProbs, data.probabilities || {});
    }

    window._probabilities = allProbs;
    const probs = Object.values(allProbs);
    const validProbs = probs.filter((p) => p.probability !== null);
    const highCount = validProbs.filter((p) => p.probability >= 65).length;
    const medCount = validProbs.filter((p) => p.probability >= 35 && p.probability < 65).length;
    const lowCount = validProbs.filter((p) => p.probability < 35).length;

    $("probabilitySummary").style.display = "";
    $("probabilitySummary").innerHTML =
      `<b>历史位次模型参考（未校准，不含选科资格）：</b>高估计值(≥65%) ${highCount}个 | 中估计值 ${medCount}个 | 低估计值(<35%) ${lowCount}个 | 数据不足 ${probs.length - validProbs.length}个`;
    render();
    showToast("概率计算完成", "success");
  } catch (err) {
    showToast("概率计算失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "计算录取概率";
}

function getProbBadge(institution, major) {
  if (!window._probabilities) return "";
  const key = `${institution}|${major}`;
  const probData = window._probabilities[key];
  if (!probData || probData.probability === null) {
    return '<span class="prob-badge prob-unknown">概率未知</span>';
  }
  const pct = probData.probability;
  let cls = pct >= 65 ? "prob-high" : pct >= 35 ? "prob-medium" : "prob-low";
  return `<span class="prob-badge ${cls}" title="${escapeHtml('历史模型估计，不含选科资格，未经录取样本校准。' + (probData.message || ''))}">历史估计 ${pct}%</span>`;
}

// ── Tab Switching ──
function initTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      const panel = document.getElementById(btn.dataset.tab);
      if (panel) panel.classList.add("active");
    });
  });
}

// ── Peer Insights ──
async function loadPeerInsights() {
  const result = getState(STORAGE_KEYS.recommendResult, {});
  const mainInput = getState(STORAGE_KEYS.mainInput, {});
  const btn = $("refreshPeerBtn");
  if (btn) { btn.disabled = true; btn.textContent = "分析中..."; }
  try {
    const data = await api("/api/v1/kg/peer-insights", "POST", {
      rank: mainInput.rank || 0,
      provinces: mainInput.provinces || [],
      majors: mainInput.majors || [],
      subject_combo: mainInput.subject_combo || "",
      rank_window: mainInput.rank_window || 1000,
      candidate_scope: mainInput.candidate_scope || "all",
      limit: 10,
      year: mainInput.year || 2024,
    });
    $("peerEmpty").classList.add("hidden");

    const popularMajors = data.popular_majors || [];
    $("peerMajors").textContent = popularMajors.map((m) =>
      `${m.major}: ${m.inst_count}所院校, 平均位次${Math.round(m.avg_rank)}`
    ).join("\n") || "暂无数据";

    const popularProvinces = data.popular_provinces || [];
    $("peerProvinces").textContent = popularProvinces.map((p) =>
      `${p.province}: ${p.inst_count}所院校`
    ).join("\n") || "暂无数据";

    const dist = data.rank_distribution || {};
    $("peerDistribution").textContent =
      `该分段总候选数: ${dist.total_candidates || "-"}\n` +
      `P25位次: ${dist.p25 || "-"} | P50位次: ${dist.p50 || "-"} | P75位次: ${dist.p75 || "-"}\n` +
      `说明: 25%的候选位次 ≤ P25, 50%的候选位次 ≤ P50`;
  } catch (err) {
    showToast("候选分布分析失败: " + (err.message || String(err)), "error");
  }
  if (btn) { btn.disabled = false; btn.textContent = "刷新分析"; }
}

// ── Market Analysis ──
async function runMarketAnalysis() {
  const result = getState(STORAGE_KEYS.recommendResult, {});
  let majorsStr = $("marketAnalysisMajors").value.trim();
  let majors;
  if (majorsStr) {
    majors = splitCsv(majorsStr).slice(0, 6);
  } else {
    majors = [...new Set((result.all || []).map((x) => x.major).filter(Boolean))].slice(0, 5);
  }
  if (!majors.length) { showToast("没有可分析的专业", "warning"); return; }

  const btn = $("runMarketAnalysisBtn");
  btn.disabled = true;
  btn.textContent = "分析中(需AI)...";
  $("marketEmpty").classList.add("hidden");

  try {
    const data = await api("/api/v1/majors/market-analysis", "POST", { majors: majors });
    const analyzed = data.data || {};

    // Radar chart
    const radarDom = $("marketRadarChart");
    if (radarDom) {
      const existing = echarts.getInstanceByDom(radarDom);
      if (existing) existing.dispose();

      const indicator = [
        { name: "需求判断", max: 100 },
        { name: "薪资潜力判断", max: 100 },
        { name: "抗自动化判断", max: 100 },
        { name: "主观综合分", max: 100 },
      ];
      const riskMap = { "低": 85, "中": 50, "高": 15 };
      const salaryMap = { "低": 30, "中": 55, "中高": 75, "高": 95 };
      const demandMap = { "增长": 90, "稳定": 60, "下降": 25 };
      const seriesData = Object.entries(analyzed).filter(([, i]) => i && i.demand_trend !== "待核实" && i.salary_potential !== "待核实" && i.automation_risk !== "待核实").map(([name, info]) => {
        const i = info || {};
        return {
          name: name.length > 6 ? name.slice(0, 6) + "..." : name,
          value: [
            demandMap[i.demand_trend],
            salaryMap[i.salary_potential],
            riskMap[i.automation_risk],
            i.market_score,
          ],
        };
      });

      const chart = echarts.init(radarDom, getEChartsTheme());
      chart.setOption({
        tooltip: { extraCssText: "max-width:280px", formatter: (p) => escapeHtml(p.name) + "<br/>AI 主观比较，非实时统计数据" },
        title: { text: "AI 主观比较", subtext: "待核实项不绘图；定性值映射仅用于展示", left: "center", textStyle: { fontSize: 14 } },
        legend: {
          data: seriesData.map((s) => s.name),
          bottom: 0,
          textStyle: { color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-secondary").trim() || "#94a3b8" },
        },
        radar: {
          indicator: indicator,
          center: ["50%", "45%"],
          radius: "65%",
          axisName: { color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-secondary").trim() || "#94a3b8" },
        },
        series: [{ type: "radar", data: seriesData }],
        backgroundColor: "transparent",
      });
    }

    // Detail text
    let detailHtml = `<p class="small">${escapeHtml(data.notice || "AI 主观比较，非实时就业统计")}</p>`;
    Object.entries(analyzed).forEach(([name, info]) => {
      const i = info || {};
      detailHtml += `<b>${escapeHtml(name)}:</b> ${escapeHtml(i.summary || "")} | 需求:${escapeHtml(i.demand_trend || "-")} | 薪资:${escapeHtml(i.salary_potential || "-")} | 自动化风险:${escapeHtml(i.automation_risk || "-")}<br/>`;
      detailHtml += `热门行业: ${escapeHtml((i.top_industries || []).join(", "))}<br/>`;
      detailHtml += `新兴岗位: ${escapeHtml((i.emerging_roles || []).join(", "))}<br/>`;
      detailHtml += `地域热点: ${escapeHtml((i.geographic_hotspots || []).join(", "))}<br/><br/>`;
    });
    $("marketDetail").innerHTML = detailHtml || escapeHtml(data.raw || "无结果");
    showToast("市场分析完成", "success");
  } catch (err) {
    showToast("市场分析失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "AI市场分析";
}

// ── Strategy Optimizer ──
async function runOptimizer() {
  const result = getState(STORAGE_KEYS.recommendResult, {});
  const mainInput = getState(STORAGE_KEYS.mainInput, {});
  const candidates = result.candidates || result.all || [];
  if (!candidates.length) { showToast("没有候选数据", "warning"); return; }

  const btn = $("runOptimizeBtn");
  btn.disabled = true;
  btn.textContent = "优化中...";

  const prefsRaw = $("optimizePrefs").value.trim();
  const prefs = {};
  if (prefsRaw) {
    splitCsv(prefsRaw).forEach((pair) => {
      const [k, v] = pair.split("=").map((s) => s.trim());
      if (k && v) prefs[k] = Number(v);
    });
  }

  try {
    if (Object.values(prefs).some((value) => !Number.isFinite(value))) throw new Error("偏好权重必须为有效数字");
    const data = await api("/api/v1/recommend/optimize", "POST", {
      rank: mainInput.rank || 0,
      candidates: candidates,
      target_count: mainInput.target_count || 80,
      ratio_chong: mainInput.ratio_chong ?? 3,
      ratio_wen: mainInput.ratio_wen ?? 4,
      ratio_bao: mainInput.ratio_bao ?? 3,
      user_preferences: prefs,
    });

    $("optimizeResult").style.display = "";
    const meta = data.meta || {};
    $("optimizeMeta").textContent =
      `总分: ${data.score || 0} | 推荐${(data.optimized || []).length}条 | ` +
      `冲${meta.layer_actual?.["冲"]||0} / 稳${meta.layer_actual?.["稳"]||0} / 保${meta.layer_actual?.["保"]||0}`;

    const list = $("optimizeList");
    list.innerHTML = "";
    (data.optimized || []).forEach((x) => {
      const div = document.createElement("div");
      div.className = "list-item";
      div.innerHTML =
        `<div class="list-item-header">` +
          `<span class="list-item-title">${escapeHtml(x.institution)} - ${escapeHtml(x.major)}</span>` +
          `<span class="list-item-meta">评分:${x._score || "-"} | ${x.layer}</span>` +
        `</div>` +
        `<div>最低位次: ${x.min_rank ?? "-"} | 最低分: ${x.min_score ?? "-"} | 层次: ${escapeHtml(x.level || "-")} | ${escapeHtml(subjectEligibilityLabel(x))}</div>`;
      list.appendChild(div);
    });
    showToast("优化完成", "success");
  } catch (err) {
    showToast("优化失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "运行优化";
}

async function regenerateRecommendations() {
  const input = getState(STORAGE_KEYS.mainInput, {});
  if (!Number.isInteger(input.rank) || input.rank < 1) { showToast("请先在工作台填写有效位次", "warning"); return; }
  const btn = $("regenerateBtn");
  btn.disabled = true;
  btn.textContent = "生成中…";
  try {
    const result = await api("/api/v1/recommend/run", "POST", input);
    if (!setState(STORAGE_KEYS.recommendResult, result)) return;
    window._probabilities = null;
    $("probabilitySummary").style.display = "none";
    render();
    showToast(`已生成 ${result.all.length} 条候选，请查看筛选说明`, "success");
  } catch (err) { showToast("重新生成失败：" + err.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "按当前条件重新生成"; }
}

window.addEventListener("DOMContentLoaded", () => {
  setupRefreshNotice(
    [STORAGE_KEYS.recommendResult, STORAGE_KEYS.compareList],
    async () => {
      $("recommendMeta").textContent = "";
      $("recommendList").innerHTML = "";
      render();
    }
  );
  render();
  $("regenerateBtn").addEventListener("click", regenerateRecommendations);
  // 院校属性保留数据库原值；缺失内容显示为待核实，避免自动调用模型猜测。
  bindFilterButtons();
  initTabs();
  $("recommendSearch").addEventListener("input", render);
  $("layerFilter").addEventListener("change", render);
  $("resetFilters").addEventListener("click", () => {
    filters.level = null; filters.nature = null;
    $("recommendSearch").value = ""; $("layerFilter").value = "";
    document.querySelectorAll("#filterGroup button:not(#resetFilters)").forEach((b) => { b.classList.remove("btn-primary"); b.setAttribute("aria-pressed", "false"); });
    render();
  });
  document.addEventListener("keydown", (e) => {
    const drawer = $("detailDrawer");
    if (drawer.classList.contains("hidden")) return;
    if (e.key === "Escape") closeDrawer();
    if (e.key === "Tab") {
      const focusable = [...drawer.querySelectorAll('button, a[href], [tabindex="0"]')];
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === drawer)) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  });
  $("openCompareBtn").addEventListener("click", () => { window.location.href = "/compare"; });
  $("loadProbabilityBtn").addEventListener("click", loadProbability);
  $("loadPeerBtn").addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    const analyzeTab = document.querySelector('[data-tab="tabAnalyze"]');
    if (analyzeTab) analyzeTab.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    const panel = document.getElementById("tabAnalyze");
    if (panel) panel.classList.add("active");
    loadPeerInsights();
  });
  $("refreshPeerBtn").addEventListener("click", loadPeerInsights);
  $("runMarketAnalysisBtn").addEventListener("click", runMarketAnalysis);
  $("runOptimizeBtn").addEventListener("click", runOptimizer);
  document.getElementById("closeDetailBtn").addEventListener("click", closeDrawer);
  document.getElementById("drawerOverlay").addEventListener("click", closeDrawer);


});
