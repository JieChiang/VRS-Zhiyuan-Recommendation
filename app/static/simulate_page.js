const $ = (id) => document.getElementById(id);

function initWhatIf() {
  const mainInput = getState(STORAGE_KEYS.mainInput, {});
  $("whatifOrigRank").textContent = mainInput.rank || "-";
  $("whatifOrigScore").textContent = mainInput.score ?? "-";
  $("whatifOrigSubject").textContent = mainInput.subject_combo || "-";
  $("whatifOrigYear").textContent = mainInput.year || "-";
  $("whatifOrigMajors").textContent = (mainInput.majors || []).join(", ") || "-";
  $("whatifOrigProvinces").textContent = (mainInput.provinces || []).join(", ") || "-";
  $("whatifNewRank").value = mainInput.rank || "";
  $("whatifNewScore").value = mainInput.score ?? "";
}

async function runWhatIf() {
  const mainInput = getState(STORAGE_KEYS.mainInput, {});
  if (!Number.isInteger(mainInput.rank) || mainInput.rank < 1) {
    showToast("请先在规划工作台填写并保存有效位次", "warning"); return;
  }
  const newRank = $("whatifNewRank").value === "" ? mainInput.rank : Number($("whatifNewRank").value);
  const newScore = $("whatifNewScore").value === "" ? (mainInput.score ?? null) : Number($("whatifNewScore").value);
  if (!Number.isInteger(newRank) || newRank < 1 || (newScore !== null && (!Number.isInteger(newScore) || newScore < 0))) {
    showToast("模拟位次须为正整数，分数须为非负整数", "warning"); return;
  }
  const newProvincesRaw = $("whatifNewProvinces").value.trim();
  const newProvinces = newProvincesRaw ? splitCsv(newProvincesRaw) : (mainInput.provinces || []);
  const newMajorsRaw = $("whatifNewMajors").value.trim();
  const newMajors = newMajorsRaw ? splitCsv(newMajorsRaw) : (mainInput.majors || []);

  const resultEl = $("whatifResult");
  resultEl.style.display = "";
  resultEl.textContent = "模拟计算中...";
  const btn = $("whatifRunBtn");
  btn.disabled = true;
  btn.textContent = "模拟中...";

  try {
    const [origResult, newResult] = await Promise.all([
      api("/api/v1/recommend/run", "POST", {
        rank: mainInput.rank || 0,
        subject_combo: mainInput.subject_combo || "",
        score: mainInput.score || 0,
        majors: mainInput.majors || [],
        provinces: mainInput.provinces || [],
        target_institutions: mainInput.target_institutions || [],
        target_count: mainInput.target_count || 80,
        ratio_chong: mainInput.ratio_chong ?? 3,
        ratio_wen: mainInput.ratio_wen ?? 4,
        ratio_bao: mainInput.ratio_bao ?? 3,
        rank_window: mainInput.rank_window || 1000,
        candidate_scope: mainInput.candidate_scope || "all",
        year: mainInput.year || 2024,
      }),
      api("/api/v1/recommend/run", "POST", {
        rank: newRank,
        subject_combo: mainInput.subject_combo || "",
        score: newScore,
        majors: newMajors,
        provinces: newProvinces,
        target_institutions: mainInput.target_institutions || [],
        target_count: mainInput.target_count || 80,
        ratio_chong: mainInput.ratio_chong ?? 3,
        ratio_wen: mainInput.ratio_wen ?? 4,
        ratio_bao: mainInput.ratio_bao ?? 3,
        rank_window: mainInput.rank_window || 1000,
        candidate_scope: mainInput.candidate_scope || "all",
        year: mainInput.year || 2024,
      }),
    ]);

    const origAll = origResult.all || [];
    const newAll = newResult.all || [];
    const origSet = new Set(origAll.map((x) => `${escapeHtml(String(x.institution ?? "—"))}|${escapeHtml(String(x.major ?? "—"))}`));
    const newSet = new Set(newAll.map((x) => `${escapeHtml(String(x.institution ?? "—"))}|${escapeHtml(String(x.major ?? "—"))}`));

    let html = `<b>原始推荐: ${origAll.length} 条 | 新推荐: ${newAll.length} 条</b><br/><br/>`;
    html += `<div>${escapeHtml([...new Set([...(origResult.meta?.warnings || []), ...(newResult.meta?.warnings || [])])].join("；"))}</div><br/>`;
    html += `<b>新增推荐 (${newAll.filter((x) => !origSet.has(`${escapeHtml(String(x.institution ?? "—"))}|${escapeHtml(String(x.major ?? "—"))}`)).length}条):</b><br/>`;
    newAll.forEach((x) => {
      const key = `${escapeHtml(String(x.institution ?? "—"))}|${escapeHtml(String(x.major ?? "—"))}`;
      if (!origSet.has(key)) {
        html += `<div class="whatif-diff-added">+ ${escapeHtml(String(x.institution ?? "—"))} - ${escapeHtml(String(x.major ?? "—"))} (位次:${escapeHtml(String(x.min_rank ?? "—"))}) [${escapeHtml(String(x.layer ?? "—"))}]</div>`;
      }
    });
    html += `<br/><b>不再推荐 (${origAll.filter((x) => !newSet.has(`${escapeHtml(String(x.institution ?? "—"))}|${escapeHtml(String(x.major ?? "—"))}`)).length}条):</b><br/>`;
    origAll.forEach((x) => {
      const key = `${escapeHtml(String(x.institution ?? "—"))}|${escapeHtml(String(x.major ?? "—"))}`;
      if (!newSet.has(key)) {
        html += `<div class="whatif-diff-removed">- ${escapeHtml(String(x.institution ?? "—"))} - ${escapeHtml(String(x.major ?? "—"))} (位次:${escapeHtml(String(x.min_rank ?? "—"))})</div>`;
      }
    });

    const origMeta = origResult.meta || {};
    const newMeta = newResult.meta || {};
    html += `<br/><b>分层对比：</b><br/>`;
    html += `原始: 冲${origMeta.layer_actual?.["冲"]||0} / 稳${origMeta.layer_actual?.["稳"]||0} / 保${origMeta.layer_actual?.["保"]||0}<br/>`;
    html += `调整: 冲${newMeta.layer_actual?.["冲"]||0} / 稳${newMeta.layer_actual?.["稳"]||0} / 保${newMeta.layer_actual?.["保"]||0}`;

    resultEl.innerHTML = html;
    showToast("模拟对比完成", "success");
  } catch (err) {
    resultEl.textContent = "模拟失败: " + (err.message || String(err));
    showToast("模拟失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "运行模拟对比";
}

window.addEventListener("DOMContentLoaded", () => {
  setupRefreshNotice(
    [STORAGE_KEYS.compareList, STORAGE_KEYS.selectedMajors, STORAGE_KEYS.recommendResult, STORAGE_KEYS.mainInput],
    () => { initWhatIf(); }
  );
  initWhatIf();
  $("whatifRunBtn").addEventListener("click", runWhatIf);
});
