const $ = (id) => document.getElementById(id);
let selectedL1 = null;
let selectedL2 = null;

function getSelectedMajors() {
  return getState(STORAGE_KEYS.selectedMajors, []);
}

function setSelectedMajors(items) {
  return setState(STORAGE_KEYS.selectedMajors, items);
}

function renderSelected() {
  const box = $("selectedMajors");
  box.innerHTML = "";
  var list = getSelectedMajors();
  toggleEmptyState("selectedMajors", list.length === 0);
  list.forEach((m) => {
    const div = document.createElement("div");
    div.className = "list-item";
    div.innerHTML =
      `<div class="list-item-header">` +
        `<span class="list-item-title">${escapeHtml(m.name)}</span>` +
        `<span class="list-item-meta">${escapeHtml(m.code || "-")}</span>` +
      `</div>` +
      `<div class="list-item-actions">` +
        `<button class="btn btn-sm btn-secondary js-del">删除</button>` +
      `</div>`;
    div.querySelector(".js-del").addEventListener("click", () => {
      setSelectedMajors(getSelectedMajors().filter((x) => x.norm_name !== m.norm_name));
      renderSelected();
    });
    box.appendChild(div);
  });
}

function hideListEmpty(listId) {
  var emptyMap = { l1List: "l1Empty", l2List: "l2Empty", l3List: "l3Empty" };
  var emptyId = emptyMap[listId];
  if (!emptyId) return;
  var el = document.getElementById(emptyId);
  if (el) el.classList.add("hidden");
  var listEl = document.getElementById(listId);
  if (listEl) listEl.classList.remove("hidden");
}

async function loadL1() {
  showLoading("l1Area");
  try {
    const data = await api("/api/v1/majors/l1");
    const list = $("l1List");
    list.innerHTML = "";
    hideListEmpty("l1List");
    data.items.forEach((x) => {
      const div = document.createElement("div");
      div.className = "list-item";
      div.style.cursor = "pointer";
      div.tabIndex = 0;
      div.setAttribute("role", "button");
      div.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); div.click(); }
      });
      div.innerHTML = `<span style="color:var(--color-text-muted);font-size:var(--font-size-xs);">${escapeHtml(x.code || "-")}</span> <span style="font-weight:500;">${escapeHtml(x.name)}</span>`;
      div.addEventListener("click", async () => {
        selectedL1 = x;
        document.querySelectorAll("#l1List .list-item").forEach(function (el) { el.style.borderColor = ""; el.style.background = ""; });
        div.style.borderColor = "var(--color-primary)";
        div.style.background = "var(--color-primary-light)";
        await loadL2(x.norm_name);
      });
      list.appendChild(div);
    });
  } catch (err) {
    showToast("加载一级专业失败: " + (err.message || String(err)), "error");
    $("l1Empty").classList.remove("hidden");
    $("l1Empty").textContent = "加载失败，可刷新页面重试";
  } finally {
    hideLoading("l1Area");
  }
}

async function loadL2(l1Norm) {
  showLoading("l2Area");
  try {
    const data = await api("/api/v1/majors/l2?l1_norm_name=" + encodeURIComponent(l1Norm));
    const list = $("l2List");
    list.innerHTML = "";
    $("l3List").innerHTML = "";
    hideListEmpty("l2List");
    data.items.forEach((x) => {
      const div = document.createElement("div");
      div.className = "list-item";
      div.style.cursor = "pointer";
      div.tabIndex = 0;
      div.setAttribute("role", "button");
      div.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); div.click(); }
      });
      div.innerHTML = `<span style="color:var(--color-text-muted);font-size:var(--font-size-xs);">${escapeHtml(x.code || "-")}</span> <span style="font-weight:500;">${escapeHtml(x.name)}</span>`;
      div.addEventListener("click", async () => {
        selectedL2 = x;
        document.querySelectorAll("#l2List .list-item").forEach(function (el) { el.style.borderColor = ""; el.style.background = ""; });
        div.style.borderColor = "var(--color-primary)";
        div.style.background = "var(--color-primary-light)";
        await loadL3(x.norm_name);
      });
      list.appendChild(div);
    });
  } catch (err) {
    showToast("加载二级专业失败: " + (err.message || String(err)), "error");
    $("l2Empty").classList.remove("hidden");
    $("l2Empty").textContent = "加载失败，可刷新页面重试";
  } finally {
    hideLoading("l2Area");
  }
}

async function loadL3(l2Norm) {
  showLoading("l3Area");
  try {
    const data = await api("/api/v1/majors/l3?l2_norm_name=" + encodeURIComponent(l2Norm));
    const list = $("l3List");
    list.innerHTML = "";
    hideListEmpty("l3List");
    data.items.forEach((x) => {
      const div = document.createElement("div");
      div.className = "list-item";
      div.innerHTML =
        `<div class="list-item-header">` +
          `<span class="list-item-title">${escapeHtml(x.code || "-")} ${escapeHtml(x.name)}</span>` +
        `</div>` +
        `<div class="list-item-actions">` +
          `<button class="btn btn-sm btn-accent js-add">选择</button>` +
        `</div>`;
      div.querySelector(".js-add").addEventListener("click", () => {
        const current = getSelectedMajors();
        if (!current.some((m) => m.norm_name === x.norm_name)) {
          current.push(x);
          if (!setSelectedMajors(current)) return;
          renderSelected();
          showToast("已添加: " + x.name, "success", 2000);
        }
      });
      list.appendChild(div);
    });
  } catch (err) {
    showToast("加载三级专业失败: " + (err.message || String(err)), "error");
    $("l3Empty").classList.remove("hidden");
    $("l3Empty").textContent = "加载失败，可刷新页面重试";
  } finally {
    hideLoading("l3Area");
  }
}

async function loadIntro() {
  const selected = getSelectedMajors();
  if (!selected.length) {
    showToast("请先选择至少一个专业", "warning");
    return;
  }
  var btn = $("loadIntroBtn");
  btn.disabled = true;
  btn.textContent = "生成中...";
  var introEmpty = document.getElementById("introEmpty");
  if (introEmpty) introEmpty.classList.add("hidden");
  try {
    const majors = selected.map((x) => x.name);
    const data = await api("/api/v1/majors/intro", "POST", { majors });
    const sources = [...new Set((data.details || []).map((d) => d.source_file).filter(Boolean))];
    $("introResult").textContent = (data.llm?.answer || "") + (sources.length ? "\n\n图谱资料来源：" + sources.join("、") : "");
    $("introResult").classList.remove("hidden");
    showToast("介绍生成完成", "success");
  } catch (err) {
    showToast("生成介绍失败: " + (err.message || String(err)), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "专业介绍";
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  setupRefreshNotice(
    [STORAGE_KEYS.selectedMajors, STORAGE_KEYS.mainInput],
    async () => {
      $("introResult").textContent = "";
      renderSelected();
    }
  );
  renderSelected();
  $("loadIntroBtn").addEventListener("click", loadIntro);
  loadL1();
});
