const $ = (id) => document.getElementById(id);
let kgChart = null;
let kgCurrentNodes = [];
let kgCurrentEdges = [];
let graphRequestId = 0;

const CATEGORY_COLORS = {
  "院校": "#1E40AF",
  "专业": "#D97706",
  "就业地区": "#10B981",
  "招生专业": "#8B5CF6",
  "专业类": "#0D9488",
  "专业门类": "#DB2777",
};

async function loadGraphData(keyword, nodeType, limit) {
  const requestId = ++graphRequestId;
  const area = $("kgGraphArea");
  showLoading("kgGraphArea");
  try {
    const data = await api("/api/v1/kg/explorer-data", "POST", {
      keyword: keyword || "",
      node_type: nodeType || "all",
      limit: limit || 50,
    });
    if (requestId !== graphRequestId) return;
    kgCurrentNodes = data.nodes || [];
    kgCurrentEdges = data.edges || [];
    $("kgNodeCount").textContent =
      `${kgCurrentNodes.length} 节点 / ${kgCurrentEdges.length} 关系`;
    renderGraph();
    $("kgGraphEmpty").classList.toggle("hidden", kgCurrentNodes.length > 0);
    $("kgGraphChart").classList.remove("hidden");
  } catch (err) {
    if (requestId !== graphRequestId) return;
    showToast("图谱加载失败: " + (err.message || String(err)), "error");
  } finally {
    if (requestId === graphRequestId) hideLoading("kgGraphArea");
  }
}

function renderGraph() {
  const dom = $("kgGraphChart");
  if (!dom) return;
  if (kgChart) {
    kgChart.dispose();
    kgChart = null;
  }

  kgChart = echarts.init(dom, getEChartsTheme());

  const categories = [
    { name: "院校", itemStyle: { color: "#1E40AF" } },
    { name: "专业", itemStyle: { color: "#D97706" } },
    { name: "就业地区", itemStyle: { color: "#10B981" } },
    { name: "招生专业", itemStyle: { color: "#8B5CF6" } },
    { name: "专业类", itemStyle: { color: "#0D9488" } },
    { name: "专业门类", itemStyle: { color: "#DB2777" } },
  ];

  const nodes = kgCurrentNodes.map((n) => ({
    id: n.id,
    name: n.name,
    category: n.category,
    symbolSize: n.category === "院校" ? 28 : n.category === "专业" ? 20 : 16,
    label: { show: n.category === "院校" || kgCurrentNodes.length <= 25 },
    itemStyle: {
      color: CATEGORY_COLORS[n.category] || "#64748B",
    },
    ...n,
  }));

  const edges = kgCurrentEdges.map((e, i) => ({
    source: e.source,
    target: e.target,
    relation: e.label || "",
    label: { show: false, formatter: e.label || "" },
    lineStyle: { color: "#94A3B8", width: 0.8, curveness: 0.15 },
  }));

  kgChart.setOption({
    tooltip: {
      trigger: "item",
      formatter: function (p) {
        if (p.dataType === "node") {
          return `${escapeHtml(p.data.category)}: <b>${escapeHtml(p.data.name)}</b><br/>${escapeHtml(p.data.province || "")} ${escapeHtml(p.data.city || "")} ${escapeHtml(p.data.l1 || "")} ${escapeHtml(p.data.l2 || "")}`;
        }
        return escapeHtml(p.data.relation || "");
      },
    },
    legend: [
      {
        data: categories.map((c) => c.name),
        orient: "horizontal",
        left: 10,
        top: 10,
        textStyle: { color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-secondary").trim() || "#94a3b8" },
      },
    ],
    series: [
      {
        type: "graph",
        layout: "force",
        data: nodes,
        links: edges,
        categories: categories,
        roam: true,
        draggable: true,
        force: {
          repulsion: 85,
          gravity: 0.15,
          edgeLength: [50, 120],
          layoutAnimation: false,
        },
        emphasis: {
          focus: "adjacency",
          lineStyle: { width: 3 },
          label: { show: true },
        },
        scaleLimit: { min: 0.3, max: 5 },
        label: {
          show: true,
          position: "right",
          fontSize: 11,
          color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-secondary").trim() || "#94a3b8",
        },
        lineStyle: {
          color: "source",
          curveness: 0.2,
        },
      },
    ],
    backgroundColor: "transparent",
  });

  kgChart.on("click", function (params) {
    if (params.dataType === "node") {
      showNodeDetail(params.data);
    }
  });


}

function showNodeDetail(node) {
  $("kgNodeDetailCard").style.display = "";
  $("kgNodeDetailTitle").textContent = `${escapeHtml(String(node.category))}: ${escapeHtml(String(node.name))}`;
  let html = `<b>类型：</b>${escapeHtml(String(node.category))}<br/>`;
  if (node.province) html += `<b>省份：</b>${escapeHtml(String(node.province))}<br/>`;
  if (node.city) html += `<b>城市：</b>${escapeHtml(String(node.city))}<br/>`;
  if (node.l1) html += `<b>一级专业：</b>${escapeHtml(String(node.l1))}<br/>`;
  if (node.l2) html += `<b>二级专业：</b>${escapeHtml(String(node.l2))}<br/>`;
  if (node.pct) html += `<b>就业占比：</b>${node.pct}%<br/>`;

  const neighbors = kgCurrentEdges.filter(
    (e) => e.source === node.id || e.target === node.id
  );
  if (neighbors.length > 0) {
    html += `<br/><b>关联关系 (${neighbors.length}条)：</b><br/>`;
    neighbors.slice(0, 20).forEach((e) => {
      const otherId = e.source === node.id ? e.target : e.source;
      const otherNode = kgCurrentNodes.find((n) => n.id === otherId);
      const otherName = otherNode ? otherNode.name : otherId;
      const dir = e.source === node.id ? "→" : "←";
      html += `${dir} ${escapeHtml(String(otherName))} <span class="text-muted">${escapeHtml(String(e.label || ""))}</span><br/>`;
    });
  }

  if (node.category === "院校") {
    html += `<br/><button class="btn btn-sm btn-accent js-career-sim" data-inst="${escapeHtml(String(node.name))}">职业路径模拟</button>`;
  }

  $("kgNodeDetailContent").innerHTML = html;

  const careerBtn = $("kgNodeDetailContent").querySelector(".js-career-sim");
  if (careerBtn) {
    careerBtn.addEventListener("click", () => {
      const inst = careerBtn.dataset.inst;
      const majorNeighbors = kgCurrentEdges
        .filter((e) => e.source === node.id)
        .map((e) => {
          const targetNode = kgCurrentNodes.find((n) => n.id === e.target);
          return targetNode && ["专业", "招生专业"].includes(targetNode.category) ? targetNode.name : null;
        })
        .filter(Boolean);
      const major = majorNeighbors[0] || "";
      if (major) {
        simulateCareer(inst, major);
      } else {
        showToast("该院校在图中无可关联的专业节点", "warning");
      }
    });
  }

  $("kgNodeDetailCard").scrollIntoView({ behavior: "smooth" });
}

async function simulateCareer(institution, major) {
  const btn = $("kgNodeDetailContent").querySelector(".js-career-sim");
  if (btn) { btn.disabled = true; btn.textContent = "模拟中..."; }
  try {
    const data = await api("/api/v1/career/simulate", "POST", {
      institution: institution,
      major: major,
      num_years: 10,
    });
    const careerData = data.data;
    let html = `<h3>${escapeHtml(String(institution))} - ${escapeHtml(String(major))} 职业发展路径</h3>`;
    html += `<p class="small">${escapeHtml(data.notice || "AI 职业情景建议")}</p>`;
    if (careerData && careerData.stages) {
      careerData.stages.forEach((s) => {
        html += `<div class="box small mb-3"><b>${escapeHtml(String(s.year_range))} (${escapeHtml(String(s.stage))})</b><br/>`;
        html += `典型岗位: ${escapeHtml(String((s.typical_roles || []).join(", ")))}<br/>`;
        html += `薪资范围: ${escapeHtml(String(s.avg_salary_range || "-"))}<br/>`;
        html += `关键技能: ${escapeHtml(String((s.key_skills || []).join(", ")))}</div>`;
      });
    }
    if (careerData && careerData.industries) {
      html += `<b>目标行业：</b><br/>`;
      careerData.industries.forEach((ind) => {
        html += `${escapeHtml(String(ind.name))}: ${escapeHtml(String(ind.demand))} - ${escapeHtml(String(ind.description))}<br/>`;
      });
    }
    if (careerData && careerData.pivot_options) {
      html += `<br/><b>可转型方向：</b>${escapeHtml(String(careerData.pivot_options.join(", ")))}<br/>`;
    }
    if (careerData && careerData.summary) {
      html += `<br/><b>总结：</b>${escapeHtml(String(careerData.summary))}`;
    }
    $("kgNodeDetailContent").innerHTML = html;
    showToast("职业模拟完成", "success");
  } catch (err) {
    showToast("职业模拟失败: " + (err.message || String(err)), "error");
  }
  if (btn) { btn.disabled = false; btn.textContent = "职业路径模拟"; }
}

window.addEventListener("DOMContentLoaded", () => {
  setupRefreshNotice([STORAGE_KEYS.compareList], () => {});
  loadGraphData("", "all", 50);

  $("kgSearchBtn").addEventListener("click", () => {
    loadGraphData($("kgSearchInput").value.trim(), $("kgNodeType").value, 80);
  });
  $("kgResetBtn").addEventListener("click", () => {
    $("kgSearchInput").value = "";
    $("kgNodeType").value = "all";
    loadGraphData("", "all", 50);
  });
  $("kgSearchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      loadGraphData($("kgSearchInput").value.trim(), $("kgNodeType").value, 80);
    }
  });
  $("kgCloseDetailBtn").addEventListener("click", () => {
    $("kgNodeDetailCard").style.display = "none";
  });

  window.addEventListener("themechange", () => {
    if (kgChart) {
      kgChart.dispose();
      kgChart = null;
      renderGraph();
    }
  });
});
