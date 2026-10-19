const $ = (id) => document.getElementById(id);

function getCompareList() {
  return getState(STORAGE_KEYS.compareList, []);
}

function setCompareList(items) {
  setState(STORAGE_KEYS.compareList, items);
}

function renderCompareList() {
  resetCompareCharts();
  const box = $("compareSelected");
  box.innerHTML = "";
  const list = getCompareList();
  toggleEmptyState("compareSelected", list.length === 0);
  list.forEach((x) => {
    const div = document.createElement("div");
    div.className = "list-item compare-item";
    div.innerHTML =
      `<div class="compare-item-row">` +
        `<div><b>${escapeHtml(x.institution)}</b> - ${escapeHtml(x.major)} (${escapeHtml(String(x.year ?? "—"))})</div>` +
        `<button class="btn btn-sm btn-secondary js-del">删除</button>` +
      `</div>`;
    div.querySelector(".js-del").addEventListener("click", () => {
      const key = `${x.institution}|${x.major}|${x.year}`;
      const newList = getCompareList().filter((c) => `${c.institution}|${c.major}|${c.year}` !== key);
      setCompareList(newList);
      renderCompareList();
    });
    box.appendChild(div);
  });
}

function calcTruncatedRange(values, fallbackMin, fallbackMax) {
  fallbackMin = fallbackMin || 0;
  fallbackMax = fallbackMax || 100;
  const valid = values.filter((v) => Number.isFinite(v));
  if (!valid.length) return { min: fallbackMin, max: fallbackMax };
  const minV = Math.min(...valid);
  const maxV = Math.max(...valid);
  if (Math.abs(maxV - minV) < 1e-9) {
    const pad = Math.max(1, Math.abs(minV) * 0.05);
    return { min: minV - pad, max: maxV + pad };
  }
  const pad = (maxV - minV) * 0.12;
  return { min: minV - pad, max: maxV + pad };
}

function formatSeriesName(institution, major) {
  const m = String(major || "").trim();
  if (!m) return institution;
  const shortMajor = m.length > 12 ? m.slice(0, 12) + "..." : m;
  return institution + " · " + shortMajor;
}

function getOrCreateChartInstance(chartDom) {
  const existing = echarts.getInstanceByDom(chartDom);
  if (existing) existing.dispose();
  return echarts.init(chartDom, getEChartsTheme());
}

function isZoomed(chart) {
  const opt = chart.getOption() || {};
  const dzList = opt.dataZoom || [];
  if (!dzList.length) return false;
  return dzList.some((dz) => {
    const s = Number(dz.start != null ? dz.start : 0);
    const e = Number(dz.end != null ? dz.end : 100);
    return s > 0.0001 || e < 99.9999;
  });
}

function ensureRestoreButton(chart, chartId) {
  const block = document.getElementById(chartId);
  if (!block) return;
  const parent = block.closest(".compare-chart-block");
  if (!parent) return;
  const btnId = "restore-" + chartId;
  let btn = parent.querySelector("#" + btnId);
  if (!btn) {
    btn = document.createElement("button");
    btn.id = btnId;
    btn.className = "btn btn-sm btn-secondary chart-restore-btn hidden";
    btn.textContent = "恢复";
    parent.appendChild(btn);
    btn.addEventListener("click", () => {
      echarts.getInstanceByDom(block)?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
      btn.classList.add("hidden");
    });
  }
  const sync = function () { btn.classList.toggle("hidden", !isZoomed(chart)); };
  if (chart.__restoreSyncHandler) chart.off("datazoom", chart.__restoreSyncHandler);
  chart.__restoreSyncHandler = sync;
  chart.on("datazoom", sync);
  sync();
}

function getAxisColors() {
  const style = getComputedStyle(document.documentElement);
  return {
    text: style.getPropertyValue('--color-text-muted').trim() || '#94a3b8',
    legend: style.getPropertyValue('--color-text-secondary').trim() || '#b0bec5',
    splitLine: style.getPropertyValue('--color-border').trim() || '#334155',
  };
}

function drawTrend(rows, chartId, valueField, title, inverse, truncated, integerValues) {
  inverse = inverse || false;
  truncated = truncated || false;
  integerValues = integerValues || false;
  const dom = document.getElementById(chartId);
  if (!dom) return;
  if (!rows.some((row) => row[valueField] !== null && row[valueField] !== undefined)) {
    echarts.getInstanceByDom(dom)?.dispose();
    dom.textContent = "当前院校专业没有可用的该项历史数据";
    return;
  }
  dom.textContent = "";
  const chart = getOrCreateChartInstance(dom);
  const ac = getAxisColors();
  const years = [...new Set(rows.map((x) => x.year))].sort();
  const pairs = [...new Set(rows.map((x) => x.institution + "｜" + (x.major || "")))];
  const allVals = [];
  const series = pairs.map((s) => {
    const parts = s.split("｜");
    return {
      name: formatSeriesName(parts[0], parts[1]),
      _pairKey: s,
      type: "line",
      connectNulls: false,
      data: years.map((y) => {
        const hit = rows.find((r) => (r.institution + "｜" + (r.major || "")) === s && r.year === y);
        const raw = hit ? hit[valueField] : null;
        if (raw === null || raw === undefined || raw === "") return null;
        const val = Number(raw);
        if (!Number.isFinite(val)) return null;
        const out = integerValues ? Math.round(val) : Math.round(val * 100) / 100;
        allVals.push(out);
        return out;
      }),
    };
  });
  const range = calcTruncatedRange(allVals, 0, 100);
  chart.setOption({
    color: ['#1E40AF', '#10b981', '#D97706', '#f472b6', '#a78bfa', '#fb923c', '#38bdf8', '#fbbf24'],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", snap: !!integerValues },
      valueFormatter: (v) => {
        if (v === null || v === undefined || v === "-") return "-";
        return integerValues ? String(Math.round(Number(v))) : Number(v).toFixed(2);
      },
    },
    legend: { top: 6, type: "scroll", textStyle: { color: ac.legend } },
    xAxis: { type: "category", data: years, axisLabel: { color: ac.text }, axisLine: { lineStyle: { color: ac.splitLine } } },
    yAxis: {
      type: "value",
      inverse: inverse,
      min: truncated ? range.min : null,
      max: truncated ? range.max : null,
      minInterval: integerValues ? 1 : 0,
      axisLabel: Object.assign({ color: ac.text }, integerValues ? { formatter: (v) => Math.round(v) } : {}),
      axisPointer: { show: true, label: { show: true } },
      splitLine: { lineStyle: { color: ac.splitLine } },
    },
    grid: { top: 36, left: 50, right: 20, bottom: 34 },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "inside", yAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, filterMode: "none", height: 16, bottom: 8, borderColor: ac.splitLine, backgroundColor: 'transparent', fillerColor: 'rgba(30,64,175,0.12)' },
      { type: "slider", yAxisIndex: 0, filterMode: "none", width: 12, right: 2, borderColor: ac.splitLine, backgroundColor: 'transparent', fillerColor: 'rgba(30,64,175,0.12)' },
    ],
    series: series.map(function (s) { var r = {}; for (var k in s) { if (k !== '_pairKey') r[k] = s[k]; } return r; }),
    backgroundColor: 'transparent',
  });
  ensureRestoreButton(chart, chartId);
}

function drawTruncatedSat(rows, chartId, categories, keys, title) {
  const dom = document.getElementById(chartId);
  if (!dom) return;
  if (!rows.length) {
    echarts.getInstanceByDom(dom)?.dispose();
    dom.textContent = "暂无满意度数据";
    return;
  }
  dom.textContent = "";
  const chart = getOrCreateChartInstance(dom);
  const ac = getAxisColors();
  const allValues = [];
  rows.forEach((r) => {
    keys.forEach((k) => {
      const v = r[k] === null || r[k] === undefined || r[k] === "" ? null : Number(r[k]);
      if (v !== null && Number.isFinite(v)) allValues.push(v);
    });
  });
  const minV = allValues.length ? Math.min(...allValues) : 0;
  const maxV = allValues.length ? Math.max(...allValues) : 5;
  const yMin = Math.max(0, Math.floor((minV - 0.2) * 10) / 10);
  const yMax = Math.min(5, Math.ceil((maxV + 0.1) * 10) / 10);

  chart.setOption({
    color: ['#1E40AF', '#10b981', '#3B82F6', '#D97706'],
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { top: 6, type: "scroll", textStyle: { color: ac.legend } },
    xAxis: {
      type: "category", data: categories,
      axisLabel: { interval: 0, rotate: 20, color: ac.text },
      axisPointer: { type: "shadow" },
    },
    yAxis: {
      type: "value", min: yMin, max: yMax,
      axisPointer: { show: true, label: { show: true } },
      axisLabel: { color: ac.text },
      splitLine: { lineStyle: { color: ac.splitLine } },
    },
    grid: { top: 48, left: 50, right: 20, bottom: 56 },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "inside", yAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, filterMode: "none", height: 16, bottom: 8, borderColor: ac.splitLine, backgroundColor: 'transparent', fillerColor: 'rgba(30,64,175,0.12)' },
      { type: "slider", yAxisIndex: 0, filterMode: "none", width: 12, right: 2, borderColor: ac.splitLine, backgroundColor: 'transparent', fillerColor: 'rgba(30,64,175,0.12)' },
    ],
    series: keys.map((k) => ({
      name: k, type: "bar",
      data: rows.map((x) => x[k] === null || x[k] === undefined || x[k] === "" ? null : Number(x[k])),
    })),
    backgroundColor: 'transparent',
  });
  ensureRestoreButton(chart, chartId);
}

function hideChartsEmpty() {
  $("compareChartsArea").classList.add("has-data");
  var el = document.getElementById("compareChartsEmpty");
  if (el) el.classList.add("hidden");
}

function resetCompareCharts() {
  $("compareChartsArea").classList.remove("has-data");
  $("compareChartsEmpty").classList.remove("hidden");
  ["planChart", "scoreChart", "rankTrendChart", "instSatChart", "majorSatChart"].forEach((id) => {
    if (window.echarts) echarts.getInstanceByDom($(id))?.dispose();
    $(id).textContent = "";
  });
}

async function loadCompare() {
  const list = getCompareList();
  const schools = [...new Set(list.map((x) => x.institution))];
  if (!schools.length) {
    resetCompareCharts();
    ["planChart", "scoreChart", "rankTrendChart", "instSatChart", "majorSatChart"].forEach((id) => {
      var dom = document.getElementById(id);
      if (dom) {
        var inst = echarts.getInstanceByDom(dom);
        if (inst) inst.dispose();
      }
    });
    return;
  }
  var btn = document.getElementById("refreshCompareBtn");
  btn.disabled = true;
  btn.textContent = "加载中...";
  showLoading("compareChartsArea");
  try {
    const mainInput = getState(STORAGE_KEYS.mainInput, {});
    const compareItems = list
      .filter((x) => x && x.institution && x.major)
      .map((x) => ({ institution: x.institution, major: x.major, year: x.year }));
    const payload = {
      institutions: schools,
      compare_items: compareItems,
      major_keyword: "",
      year: mainInput.year || 2024,
    };
    const data = await api("/api/v1/compare/data", "POST", payload);
    hideChartsEmpty();
    const trend = data.trend || [];
    drawTrend(trend, "planChart", "avg_plan_count", "历年计划人数趋势", false, false, true);
    drawTrend(trend, "scoreChart", "avg_min_score", "历年专业最低分趋势（截断）", false, true, false);
    drawTrend(trend, "rankTrendChart", "avg_min_rank", "历年专业最低位次趋势（截断，Y轴反转）", true, true, false);

    const instRows = (data.institution_satisfaction || []).map((x) => ({
      institution: x.institution, "综合": x.overall, "环境": x.environment, "生活": x.life,
    }));
    drawTruncatedSat(instRows, "instSatChart",
      instRows.map((x) => x.institution),
      ["综合", "环境", "生活"], "院校满意度（截断图）");

    const majorRows = (data.major_satisfaction || []).map((x) => ({
      label: x.institution + "｜" + x.major,
      "综合": x.overall, "就业": x.employment, "教学": x.teaching, "条件": x.condition,
    }));
    drawTruncatedSat(majorRows, "majorSatChart",
      majorRows.map((x) => x.label),
      ["综合", "就业", "教学", "条件"], "专业满意度（截断图）");
  } catch (err) {
    showToast("加载对比信息失败：" + (err.message || err), "error");
  } finally {
    hideLoading("compareChartsArea");
    btn.disabled = false;
    btn.textContent = "加载对比信息";
  }
}

window.addEventListener("DOMContentLoaded", () => {
  setupRefreshNotice(
    [STORAGE_KEYS.compareList, STORAGE_KEYS.recommendResult],
    async () => {
      renderCompareList();
      await loadCompare();
    }
  );
  renderCompareList();
  document.getElementById("refreshCompareBtn").addEventListener("click", loadCompare);


});
