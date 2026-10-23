// Runs in the actual recommendation page via verify_recommendation_export.py.
(async () => {
  let checks = 0;
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
    checks++;
  };
  const search = $("recommendSearch"), scope = $("exportScope"), button = $("exportRecommendationsBtn");
  const originalFetch = window.fetch;
  try {
    assert(button.disabled, "Empty results must disable export");
    const rows = [
      {institution: "示例公办大学", major: "计算机科学与技术", year: 2024, layer: "冲", level: "本科", school_nature: "公办", min_rank: 10000, min_score: 600, plan_count: 0,
        subject_requirement_kind: "restricted", subject_eligibility: "eligible", subject_requirement_display: "物理和化学", source_file: "专业分数线.xlsx", source_sheet: "浙江", source_row: 25},
      {institution: "示例民办学院", major: "会计学", year: 2024, layer: "稳", level: "本科", school_nature: "民办", min_rank: 11100, min_score: null, plan_count: null,
        subject_requirement_kind: "unrestricted", subject_eligibility: "eligible", subject_requirement_display: "不限选科"},
      {institution: "示例职业学院", major: "计算机应用技术", year: 2024, layer: "保", level: "专科", school_nature: "公办", min_rank: 12000,
        subject_requirement_kind: "unknown", subject_eligibility: "unknown", subject_missing: ["化学"]},
      {institution: "示例属性缺失学校", major: "其他专业", year: 2024, layer: "保", min_rank: 13000},
    ];
    const result = {all: rows, pending_candidates: [{institution: "待核实学校", major: "未确认专业"}], meta: {
      recommendation_version: RECOMMENDATION_VERSION, dataset_id: GRAPH_DATASET_ID, reference_year: 2024,
      generated_at: "2026-10-23T08:00:00+00:00", input_snapshot: {rank: 11100, subject_combo: "物理、化学、地理"},
    }};
    setState(STORAGE_KEYS.recommendResult, result);
    setState(STORAGE_KEYS.mainInput, {rank: 99999});
    render();
    assert(!button.disabled && recommendationExportPayload().items.length === 4, "Default export must contain all visible rows");
    assert(recommendationExportPayload().meta.input_snapshot.rank === 11100, "Export must use generation snapshot, not edited form");
    search.value = "计算机";
    search.dispatchEvent(new Event("input"));
    assert(document.querySelectorAll("#recommendList article").length === 2, "Search must render two matches");
    assert(recommendationExportPayload().items.length === 2, "Export must match visible search results");
    $("filterBachelor").click();
    assert(recommendationExportPayload().items.length === 1, "Level and search must intersect");
    $("filterPublic").click();
    $("layerFilter").value = "冲";
    $("layerFilter").dispatchEvent(new Event("change"));
    assert(recommendationExportPayload().items[0].institution === rows[0].institution, "Combined filters must keep the correct row");
    search.value = "不存在";
    search.dispatchEvent(new Event("input"));
    assert(button.disabled, "No matches must disable export");
    scope.value = "all";
    scope.dispatchEvent(new Event("change"));
    assert(!button.disabled, "All scope must ignore empty page filter");
    assert(JSON.stringify(recommendationExportPayload().items) === JSON.stringify(rows), "All scope must preserve order and exclude separate pending records");

    // Test real blob response and download, including duplicate-click protection.
    let calls = 0;
    window.fetch = async (...args) => { calls++; return originalFetch(...args); };
    await Promise.all([exportRecommendations(), exportRecommendations()]);
    assert(calls === 1, "Duplicate clicks must send only one request");
    assert(!button.disabled && button.textContent === "导出 Excel", "Successful export must restore the button");

    window.fetch = async () => new Response(JSON.stringify({detail: "请先登录"}), {status: 401});
    await exportRecommendations();
    assert($("toastContainer").textContent.includes("登录已过期"), "Expired login must show a useful message");
    assert(!button.disabled, "Login failure must allow retry");
    window.fetch = async () => { throw new Error("模拟网络错误"); };
    await exportRecommendations();
    assert($("toastContainer").textContent.includes("模拟网络错误") && !button.disabled, "Network failure must restore controls");
    window.fetch = async () => new Response("<html>error</html>", {status: 200, headers: {"content-type": "text/html"}});
    await exportRecommendations();
    assert($("toastContainer").textContent.includes("服务返回格式异常"), "HTML must not be downloaded as an Excel file");

    $("resetFilters").click();
    scope.value = "visible";
    $("filterPrivate").click();
    assert(recommendationExportPayload().items.length === 1 && recommendationExportPayload().items[0].institution === rows[1].institution,
      "Private filter must exclude unknown properties");
    $("resetFilters").click();
    $("filterCollege").click();
    assert(recommendationExportPayload().items.length === 1 && recommendationExportPayload().items[0].institution === rows[2].institution,
      "College filter must match rendering");
    $("resetFilters").click();
    $("toastContainer").replaceChildren();
    render();
    window.exportVerification = {done: true, checks};
  } catch (error) {
    window.exportVerification = {done: true, checks, error: error.stack || String(error)};
  } finally { window.fetch = originalFetch; }
})();
