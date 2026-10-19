const GRAPH_DATASET_ID = "zhejiang-admissions-2019-2024-v2";
const RECOMMENDATION_VERSION = "preferences-v6";
const STORAGE_KEYS = {
  mainInput: "vrs.mainInput",
  recommendResult: "vrs.recommendResult",
  compareList: "vrs.compareList",
  selectedMajors: "vrs.selectedMajors",
  stateVersion: "vrs.stateVersion",
};

async function api(url, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== null) opt.body = JSON.stringify(body);
  const res = await fetch(url, opt);
  if (res.redirected && new URL(res.url).pathname === "/login") {
    throw new Error("登录已过期，请重新登录");
  }
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => `${(item.loc || []).filter((x) => x !== "body").join(".")}：${item.msg}`).join("；")
      : (typeof detail === "string" ? detail : `请求失败（${res.status}），请稍后重试`);
    throw new Error(message);
  }
  if (!isJson) throw new Error("服务返回格式异常，请刷新页面后重试");
  return data;
}

function splitCsv(text) {
  return (text || "").trim().replace(/^[（(](.*)[）)]$/, "$1").split(/[，,、；;]/).map((x) => x.trim()).filter(Boolean);
}

function subjectEligibilityLabel(item) {
  if (item.subject_requirement_kind === "unrestricted") return "不限选科";
  if (item.subject_eligibility === "eligible") return "选科符合计划原文";
  return "选科待核实" + (item.subject_missing?.length ? " · 需确认" + item.subject_missing.join("、") : "");
}

function getState(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch (_) {
    return fallback;
  }
}

function setState(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    localStorage.setItem(STORAGE_KEYS.stateVersion, String(Date.now()));
    window.dispatchEvent(new CustomEvent("vrs:statechange", { detail: { key } }));
    return true;
  } catch (_) {
    showToast("本机存储不可用或已满，请减少成绩图片后重试；本次内容未保存", "error");
    return false;
  }
}

function openOrFocusPage(url, windowName) {
  const w = window.open(url, windowName);
  if (w) w.focus();
}

function setupRefreshNotice(watchedKeys, onRefresh) {
  const notice = document.getElementById("refreshNotice");
  const refreshBtn = document.getElementById("refreshBtn");
  if (!notice || !refreshBtn) return;
  refreshBtn.addEventListener("click", async () => {
    if (typeof onRefresh === "function") {
      await onRefresh();
    } else {
      location.reload();
      return;
    }
    notice.classList.add("hidden");
  });
  window.addEventListener("storage", (e) => {
    if (e.key === null || watchedKeys.includes(e.key)) {
      notice.classList.remove("hidden");
    }
  });
}

/* ================================================================
   UX UTILITIES
   ================================================================ */

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ── Toast System ──

function initToastContainer() {
  if (document.getElementById("toastContainer")) return;
  const container = document.createElement("div");
  container.className = "toast-container";
  container.id = "toastContainer";
  document.body.appendChild(container);
}

function showToast(message, type, duration) {
  type = type || "info";
  duration = duration || 3500;
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = "toast toast-" + type;
  toast.innerHTML = "<span>" + escapeHtml(message) + "</span>";
  container.appendChild(toast);
  setTimeout(function () {
    toast.classList.add("toast-exit");
    toast.addEventListener("animationend", function () { toast.remove(); });
    setTimeout(function () { toast.remove(); }, 500);
  }, duration);
}

// ── Loading Helpers ──

function showLoading(containerId) {
  var el = document.getElementById(containerId);
  if (!el) return;
  if (el.querySelector(".loading-overlay")) return;
  var overlay = document.createElement("div");
  overlay.className = "loading-overlay";
  overlay.innerHTML = '<div class="spinner"></div>';
  if (getComputedStyle(el).position === "static") el.style.position = "relative";
  el.appendChild(overlay);
}

function hideLoading(containerId) {
  var el = document.getElementById(containerId);
  if (!el) return;
  var overlay = el.querySelector(".loading-overlay");
  if (overlay) overlay.remove();
}

// ── Safe API Call (error boundary) ──

function safeApiCall(apiCallFn, options) {
  options = options || {};
  var loadingId = options.loadingContainerId || null;
  var errorId = options.errorContainerId || null;
  var errorMsg = options.errorMessage || "操作失败";
  var onError = options.onError || null;

  if (loadingId) showLoading(loadingId);
  return apiCallFn().catch(function (err) {
    var msg = err.message || String(err);
    showToast(errorMsg + ": " + msg, "error");
    if (errorId) {
      var el2 = document.getElementById(errorId);
      if (el2) {
        el2.innerHTML = '<div class="error-state"><span class="error-message">' + escapeHtml(msg) + '</span><button class="btn btn-sm btn-secondary error-retry" onclick="location.reload()">重试</button></div>';
      }
    }
    if (onError) onError(err);
    throw err;
  }).finally(function () {
    if (loadingId) hideLoading(loadingId);
  });
}

// ── Empty State Toggle ──

function toggleEmptyState(listId, isEmpty) {
  var container = document.getElementById(listId);
  if (!container) return;
  var parent = container.parentElement;
  if (!parent) return;
  var emptyEl = parent.querySelector(".empty-state");
  if (emptyEl) {
    if (isEmpty) {
      emptyEl.classList.remove("hidden");
      container.classList.add("hidden");
    } else {
      emptyEl.classList.add("hidden");
      container.classList.remove("hidden");
    }
  }
}

// ── ECharts Theme ──

function getEChartsTheme() {
  var theme = document.documentElement.getAttribute("data-theme");
  return theme === "dark" ? "dark" : undefined;
}

function refreshChartColors() {
  if (!window.echarts) return;
  const style = getComputedStyle(document.documentElement);
  const color = style.getPropertyValue("--color-text-secondary").trim();
  const border = style.getPropertyValue("--color-border").trim();
  document.querySelectorAll(".chart, .radar-chart, .trajectory-chart, .sankey-chart").forEach((dom) => {
    const chart = window.echarts.getInstanceByDom(dom);
    if (!chart) return;
    const option = chart.getOption();
    const update = { backgroundColor: "transparent", textStyle: { color } };
    ["title", "legend"].forEach((key) => {
      if (option[key]?.length) update[key] = option[key].map(() => ({ textStyle: { color } }));
    });
    ["xAxis", "yAxis"].forEach((key) => {
      if (option[key]?.length) update[key] = option[key].map(() => ({ axisLabel: { color }, nameTextStyle: { color }, splitLine: { lineStyle: { color: border } } }));
    });
    if (option.radar?.length) update.radar = option.radar.map(() => ({ axisName: { color } }));
    chart.setOption(update);
    chart.resize();
  });
}

// ── Sidebar ──

function initSidebar() {
  var sidebar = document.getElementById("sidebar");
  var toggle = document.getElementById("sidebarToggle");
  if (!sidebar || !toggle) return;

  var collapsed = localStorage.getItem("vrs.sidebarCollapsed") === "true";
  if (collapsed) document.body.classList.add("sidebar-collapsed");
  toggle.setAttribute("aria-expanded", String(!collapsed));

  toggle.addEventListener("click", function () {
    if (window.matchMedia("(max-width: 768px)").matches) {
      sidebar.classList.remove("mobile-open");
      document.getElementById("sidebarMobileOverlay")?.classList.remove("show");
      document.getElementById("mobileNavToggle")?.setAttribute("aria-expanded", "false");
      return;
    }
    document.body.classList.toggle("sidebar-collapsed");
    var isCollapsed = document.body.classList.contains("sidebar-collapsed");
    localStorage.setItem("vrs.sidebarCollapsed", String(isCollapsed));
    toggle.setAttribute("aria-expanded", String(!isCollapsed));
  });

  // Active nav item
  var currentPath = window.location.pathname;
  document.querySelectorAll(".nav-item[data-page]").forEach(function (item) {
    var page = item.dataset.page;
    var isActive = false;
    if (page === "main" && (currentPath === "/" || currentPath === "")) isActive = true;
    if (currentPath.indexOf("/" + page) === 0) isActive = true;
    if (isActive) item.classList.add("active");
    else item.classList.remove("active");
    if (isActive) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });

  // Nav clicks
  var navRecommend = document.getElementById("navRecommend");
  var navCompare = document.getElementById("navCompare");
  var navMajors = document.getElementById("navMajors");

  if (navRecommend) {
    navRecommend.addEventListener("click", function () {
      window.location.href = "/recommend";
    });
  }
  if (navCompare) {
    navCompare.addEventListener("click", function () {
      window.location.href = "/compare";
    });
  }
  if (navMajors) {
    navMajors.addEventListener("click", function () {
      window.location.href = "/majors";
    });
  }
  var navTrajectory = document.getElementById("navTrajectory");
  var navSimulate = document.getElementById("navSimulate");
  var navKgExplorer = document.getElementById("navKgExplorer");

  if (navTrajectory) {
    navTrajectory.addEventListener("click", function () {
      window.location.href = "/trajectory";
    });
  }
  if (navSimulate) {
    navSimulate.addEventListener("click", function () {
      window.location.href = "/simulate";
    });
  }
  if (navKgExplorer) {
    navKgExplorer.addEventListener("click", function () {
      window.location.href = "/kg-explorer";
    });
  }

  // Update compare badge
  updateCompareBadge();
  window.addEventListener("vrs:statechange", function (e) {
    if (e.detail.key === STORAGE_KEYS.compareList) updateCompareBadge();
  });
  window.addEventListener("storage", function (e) {
    if (e.key === STORAGE_KEYS.compareList || e.key === STORAGE_KEYS.stateVersion) {
      updateCompareBadge();
    }
  });

  // Mobile nav toggle
  var mobileToggle = document.getElementById("mobileNavToggle");
  var mobileOverlay = document.getElementById("sidebarMobileOverlay");
  if (mobileToggle && mobileOverlay) {
    mobileToggle.setAttribute("aria-controls", "sidebar");
    mobileToggle.setAttribute("aria-expanded", "false");
    mobileToggle.addEventListener("click", function () {
      sidebar.classList.toggle("mobile-open");
      mobileOverlay.classList.toggle("show");
      mobileToggle.setAttribute("aria-expanded", String(sidebar.classList.contains("mobile-open")));
    });
    mobileOverlay.addEventListener("click", function () {
      sidebar.classList.remove("mobile-open");
      mobileOverlay.classList.remove("show");
      mobileToggle.setAttribute("aria-expanded", "false");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && sidebar.classList.contains("mobile-open")) {
        mobileOverlay.click();
        mobileToggle.focus();
      }
    });
  }
}

function updateCompareBadge() {
  var badge = document.getElementById("compareBadge");
  if (!badge) return;
  var list = getState(STORAGE_KEYS.compareList, []);
  if (list.length > 0) {
    badge.style.display = "";
    badge.textContent = String(list.length);
  } else {
    badge.style.display = "none";
  }
}

// ── Theme Toggle ──

function initThemeToggle() {
  var toggle = document.getElementById("themeToggle");
  if (!toggle) return;
  var saved = localStorage.getItem("vrs.theme") || "light";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeIcon(saved);

  toggle.addEventListener("click", function () {
    var current = document.documentElement.getAttribute("data-theme");
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("vrs.theme", next);
    updateThemeIcon(next);
    showToast(next === "dark" ? "已切换至暗色模式" : "已切换至亮色模式", "info", 2000);
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
  });
}

function updateThemeIcon(theme) {
  var toggle = document.getElementById("themeToggle");
  if (!toggle) return;
  var icon = document.getElementById("themeIcon");
  if (!icon) return;
  if (theme === "dark") {
    icon.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>';
  } else {
    icon.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
  }
}

// Shared diagnostics on every page; never place credentials in the DOM.
function initConfigurationChecks() {
  const dialog = document.getElementById("configurationDialog");
  if (!dialog) return;
  const badge = document.getElementById("configurationBadge");
  const items = document.getElementById("configurationItems");
  const refresh = document.getElementById("configurationRefresh");
  const verify = document.getElementById("configurationVerify");
  const banner = document.createElement("div");
  banner.className = "configuration-banner";
  banner.setAttribute("role", "status");
  const summary = document.createElement("span");
  summary.textContent = "正在检查 API Key 与外围软件配置…";
  const open = document.createElement("button");
  open.className = "btn btn-ghost btn-sm";
  open.textContent = "查看配置";
  const show = () => dialog.showModal();
  open.addEventListener("click", show);
  banner.append(summary, open);
  document.getElementById("mainContent")?.prepend(banner);
  document.getElementById("configurationOpen").addEventListener("click", show);
  document.getElementById("configurationClose").addEventListener("click", () => dialog.close());
  let status;
  function render() {
    const components = status.components;
    items.replaceChildren();
    ["neo4j", "deepseek", "ocr"].forEach((key) => {
      const component = components[key];
      const section = document.createElement("section");
      section.className = "configuration-item";
      const heading = document.createElement("h3");
      heading.textContent = component.name;
      const chip = document.createElement("span");
      chip.className = "chip " + (component.state === "ok" ? "chip-success" : component.state === "error" ? "chip-error" : "chip-warning");
      chip.textContent = component.title;
      const detail = document.createElement("p");
      detail.className = "field-help";
      detail.textContent = component.detail;
      const link = document.createElement("a");
      link.textContent = "安装 / 配置说明 ↗";
      link.href = component.docs_url;
      link.target = "_blank"; link.rel = "noopener noreferrer";
      section.append(heading, chip, detail, link);
      items.append(section);
    });
    const model = components.deepseek;
    const good = status.data_ready && model.verified && components.ocr.ready;
    summary.textContent = (status.data_ready ? "图谱已就绪" : "图谱需配置") + " · " + (model.verified ? "API 验证通过" : model.state === "error" ? "API 连接待修复" : model.configured ? "API Key 已填写（待验证）" : "API Key 未填写") + " · " + (components.ocr.ready ? "OCR 可用" : "OCR 待配置（可选）");
    badge.textContent = good ? "环境配置可用" : "环境与 API 配置";
    banner.classList.toggle("configuration-warning", !status.data_ready || !model.configured);
    verify.disabled = !model.configured;
  }
  async function load() {
    refresh.disabled = true;
    try {
      status = await api("/api/v1/setup/status");
      render();
    } catch (error) {
      badge.textContent = "配置检查失败";
      summary.textContent = "环境检查失败，请查看配置。";
      items.textContent = error.message;
    } finally { refresh.disabled = false; }
  }
  refresh.addEventListener("click", load);
  verify.addEventListener("click", async () => {
    if (!status) return;
    verify.disabled = true; verify.textContent = "验证中…";
    try {
      status.components.deepseek = await api("/api/v1/setup/verify-model", "POST");
      render();
    } catch (error) { showToast(error.message, "error"); }
    finally { verify.disabled = !status?.components.deepseek.configured; verify.textContent = "验证 API 连接"; }
  });
  load();
}

// ── Init ──

document.addEventListener("DOMContentLoaded", function () {
  initToastContainer();
  const cached = getState(STORAGE_KEYS.recommendResult, null);
  if (cached && cached.meta?.dataset_id !== GRAPH_DATASET_ID) {
    setState(STORAGE_KEYS.recommendResult, {});
  }
  document.getElementById("toastContainer").setAttribute("role", "status");
  document.getElementById("toastContainer").setAttribute("aria-live", "polite");
  initSidebar();
  initThemeToggle();
  initConfigurationChecks();
  window.addEventListener("themechange", refreshChartColors);
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(function (entries) {
      if (!window.echarts) return;
      entries.forEach(function (entry) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          window.echarts.getInstanceByDom(entry.target)?.resize();
        }
      });
    });
    document.querySelectorAll(".chart, .radar-chart, .trajectory-chart, .sankey-chart").forEach((el) => observer.observe(el));
  }
});
