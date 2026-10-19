const $ = (id) => document.getElementById(id);
const MOCK_EXAM_KEY = "vrs.mockExams";

function collectMainInput() {
  const ratioArr = splitCsv($("ratio").value).map((x) => Number(x || 0));
  return {
    source_province: "浙江",
    score: $("score").value === "" ? null : Number($("score").value),
    rank: Number($("rank").value || 0),
    year: Number($("year").value || 2024),
    subject_combo: $("subjectCombo").value.trim(),
    majors: splitCsv($("majors").value),
    provinces: splitCsv($("provinces").value),
    target_institutions: splitCsv($("targets").value),
    mock_exams: getState(MOCK_EXAM_KEY, []).map(({ id, source, raw_text, ocr_text }) => ({ id, source, raw_text, ocr_text })),
    rank_window: Number($("rankWindow").value || 1000),
    candidate_scope: $("candidateScope").value,
    target_count: Number($("targetCount").value || 80),
    ratio_chong: ratioArr[0] ?? 3,
    ratio_wen: ratioArr[1] ?? 4,
    ratio_bao: ratioArr[2] ?? 3,
    extra_note: $("extraNote").value.trim(),
  };
}

function fillMainInput(data) {
  if (!data) return;
  $("score").value = data.score ?? "";
  $("rank").value = data.rank ?? "";
  $("year").value = data.year ?? 2024;
  $("subjectCombo").value = data.subject_combo || "";
  $("majors").value = (data.majors || []).join(",");
  $("provinces").value = (data.provinces || []).join(",");
  $("targets").value = (data.target_institutions || []).join(",");
  $("rankWindow").value = data.rank_window ?? 1000;
  $("candidateScope").value = data.candidate_scope || "all";
  $("targetCount").value = data.target_count ?? 80;
  $("ratio").value = `${data.ratio_chong ?? 3},${data.ratio_wen ?? 4},${data.ratio_bao ?? 3}`;
  $("extraNote").value = data.extra_note || "";
}

function getMockExams() {
  return getState(MOCK_EXAM_KEY, []);
}

function setMockExams(records) {
  return setState(MOCK_EXAM_KEY, records);
}

function renderMockExams() {
  const box = $("mockExamList");
  box.innerHTML = "";
  const records = getMockExams();
  toggleEmptyState("mockExamList", records.length === 0);
  records.forEach((rec) => {
    const div = document.createElement("div");
    div.className = "item";
    const imgLinks = (rec.images || [])
      .map(
        (img, idx) =>
          `<button type="button" class="btn btn-secondary btn-sm js-view" data-index="${idx}" title="点击查看">${escapeHtml(img.name)}</button>`
      )
      .join("");
    div.innerHTML = `
      <div><b>考试记录</b> (${escapeHtml(rec.id)})</div>
      <label>成绩文本（可手动输入，支持与图片混用）<textarea class="js-raw">${escapeHtml(rec.raw_text || "")}</textarea></label>
      <label class="file-label">上传成绩图片（可多张）
        <input type="file" class="js-img" accept="image/*" multiple />
      </label>
      <div class="img-links">${imgLinks || "<span class='small'>暂无图片</span>"}</div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm js-del">删除</button>
      </div>
    `;
    div.querySelector(".js-raw").addEventListener("input", (e) => {
      rec.raw_text = e.target.value;
      const all = getMockExams().map((x) => (x.id === rec.id ? rec : x));
      setMockExams(all);
    });
    div.querySelector(".js-img").addEventListener("change", async (e) => {
      const files = Array.from(e.target.files || []);
      e.target.disabled = true;
      try { await uploadImagesForRecord(rec.id, files); }
      catch (err) { showToast("图片处理失败：" + err.message, "error"); }
      finally { e.target.value = ""; e.target.disabled = false; }
    });
    div.querySelectorAll(".js-view").forEach((el) => {
      el.addEventListener("click", () => {
        const idx = Number(el.dataset.index);
        const img = (rec.images || [])[idx];
        if (!img?.data_url || !/^data:image\/(png|jpeg|gif|webp|bmp);base64,/i.test(img.data_url)) return;
        const w = window.open("", "_blank");
        if (!w) return;
        w.opener = null;
        w.document.title = img.name;
        const preview = w.document.createElement("img");
        preview.src = img.data_url;
        preview.style.maxWidth = "100%";
        w.document.body.appendChild(preview);
      });
    });
    div.querySelector(".js-del").addEventListener("click", () => {
      setMockExams(getMockExams().filter((x) => x.id !== rec.id));
      renderMockExams();
    });
    box.appendChild(div);
  });
}

function addTextRecord() {
  const records = getMockExams();
  records.push({
    id: `mock_${Date.now()}`,
    source: "mixed",
    raw_text: "",
    ocr_text: "",
    images: [],
  });
  setMockExams(records);
  renderMockExams();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function uploadImagesForRecord(recordId, files) {
  const records = getMockExams();
  const rec = records.find((x) => x.id === recordId);
  if (!rec) return;
  rec.images = rec.images || [];
  for (const file of files) {
    if (!/^image\/(png|jpeg|gif|webp|bmp)$/.test(file.type) || file.size > 2 * 1024 * 1024) {
      showToast("请选择不超过 2 MB 的 PNG、JPEG、GIF、WebP 或 BMP 图片", "warning");
      continue;
    }
    const dataUrl = await fileToDataUrl(file);
    rec.images.push({ name: file.name, data_url: dataUrl });

    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/v1/mock-exams/ocr", { method: "POST", body: formData });
    if (!res.ok) {
      const msg = await res.text();
      showToast(`OCR失败: ${msg}`, "error");
    } else {
      const data = await res.json();
      const piece = (data.ocr_text || "").trim();
      if (piece) {
        rec.ocr_text = `${rec.ocr_text || ""}\n[${file.name}]\n${piece}\n`.trim();
      }
    }
  }
  setMockExams(records);
  renderMockExams();
}

async function formatMockExams() {
  const records = getMockExams();
  if (!records.length) { showToast("请先新增成绩记录", "warning"); return; }
  const normalized = records.map((r) => ({
    id: r.id,
    source: r.source || "mixed",
    raw_text: (r.raw_text || "").trim(),
    ocr_text: (r.ocr_text || "").trim(),
    image_names: (r.images || []).map((x) => x.name),
  }));
  const hasAnyText = normalized.some((r) => r.raw_text || r.ocr_text);
  if (!hasAnyText) {
    showToast("请先输入文本或上传可识别的成绩图片", "warning");
    return;
  }
  const btn = $("formatMockBtn");
  btn.disabled = true;
  btn.textContent = "格式化中...";
  try {
    const user_hint = $("extraNote").value.trim();
    const data = await api("/api/v1/mock-exams/format", "POST", { records: normalized, user_hint });
    $("formattedMockText").value = data.formatted?.answer || "";
    setState("vrs.mockFormatted", $("formattedMockText").value);
    showToast("格式化完成", "success");
  } catch(err) {
    showToast("格式化失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "格式化输出（云端）";
}

async function analyzeMockExams() {
  const formatted_text = $("formattedMockText").value.trim();
  if (!formatted_text) { showToast("请先格式化成绩文本", "warning"); return; }
  const btn = $("analyzeMockBtn");
  btn.disabled = true;
  btn.textContent = "分析中...";
  try {
    const user_hint = $("extraNote").value.trim();
    const data = await api("/api/v1/mock-exams/analyze", "POST", { formatted_text, user_hint });
    $("mockAnalyzeResult").textContent = data.analysis?.answer || "";
    setState("vrs.mockAnalysis", $("mockAnalyzeResult").textContent);
    showToast("分析完成", "success");
  } catch(err) {
    showToast("分析失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "优势专业 / 领域分析（云端）";
}

async function openRecommendPage() {
  if (!validateMainInput()) return;
  const mainInput = collectMainInput();
  if (!setState(STORAGE_KEYS.mainInput, mainInput)) return;
  const btn = $("openRecommendBtn");
  btn.disabled = true;
  btn.textContent = "生成中...";
  try {
  const result = await api("/api/v1/recommend/run", "POST", {
    score: mainInput.score,
    rank: mainInput.rank,
    subject_combo: mainInput.subject_combo,
    majors: mainInput.majors,
    provinces: mainInput.provinces,
    target_institutions: mainInput.target_institutions,
    target_count: mainInput.target_count,
    ratio_chong: mainInput.ratio_chong,
    ratio_wen: mainInput.ratio_wen,
    ratio_bao: mainInput.ratio_bao,
    rank_window: mainInput.rank_window,
    candidate_scope: mainInput.candidate_scope,
    year: mainInput.year,
  });
  if (!setState(STORAGE_KEYS.recommendResult, result)) return;
  } catch(err) {
    showToast("推荐生成失败: " + (err.message || String(err)), "error");
    btn.disabled = false;
    btn.textContent = "生成志愿推荐";
    return;
  }
  finally { btn.disabled = false; btn.textContent = "生成志愿推荐"; }
  window.location.href = "/recommend";
}

function openMajorsPage() {
  const mainInput = collectMainInput();
  setState(STORAGE_KEYS.mainInput, mainInput);
  window.location.href = "/majors";
}

async function askCloud() {
  const question = $("question").value.trim();
  if (!question) return;
  const btn = $("askBtn");
  btn.disabled = true;
  btn.textContent = "思考中...";
  const chatEmpty = document.getElementById("chatEmpty");
  if (chatEmpty) chatEmpty.classList.add("hidden");
  try {
    const context = collectMainInput();
    setState(STORAGE_KEYS.mainInput, context);
    const data = await api("/api/v1/chat/cloud", "POST", { question, context });
    $("chatResult").textContent = data.answer || "";
    $("chatSources").classList.toggle("hidden", !data.sources?.length);
    $("chatSourceList").textContent = (data.sources || []).map((s) => `${s.institution} · ${s.major} · ${s.year}年：${s.source_file} / ${s.source_sheet || ""} / 第${s.source_row}行`).join("\n");
    $("chatResult").classList.remove("hidden");
  } catch(err) {
    showToast("问答失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "发送问题";
}

function validateMainInput() {
  const ids = ["rank", "score", "year", "rankWindow", "targetCount", "ratio"];
  ids.forEach((id) => { $(id).removeAttribute("aria-invalid"); $(id).setCustomValidity?.(""); });
  let invalid = ids.slice(0, -1).find((id) => !$(id).disabled && (!$(id).checkValidity() ||
    ($(id).value !== "" && !Number.isInteger(Number($(id).value)))));
  const parts = $("ratio").value.split(/[,，]/).map((x) => x.trim());
  if (!invalid && (parts.length !== 3 || parts.some((x) => !/^\d+$/.test(x)) ||
      parts.some((x) => !Number.isSafeInteger(Number(x))) || parts.every((x) => Number(x) === 0))) invalid = "ratio";
  const messages = { rank: "请填写大于 0 的整数位次", score: "分数应为不小于 0 的整数", year: "参考数据年份应为 2010–2100 的整数", rankWindow: "位次窗口应为 50–100000 的整数", targetCount: "推荐总数应为 10–300 的整数", ratio: "冲稳保请填写三个非负整数，以逗号分隔，且不能同时为 0" };
  $("inputError").classList.toggle("hidden", !invalid);
  if (invalid) {
    $("inputError").textContent = messages[invalid];
    const details = $(invalid).closest("details");
    if (details) details.open = true;
    $(invalid).setAttribute("aria-invalid", "true");
    $(invalid).focus();
    return false;
  }
  return true;
}

function saveDraft() {
  const success = setState(STORAGE_KEYS.mainInput, collectMainInput());
  $("draftStatus").textContent = success ? "草稿已保存 · 本机" : "草稿未保存";
  return success;
}

window.addEventListener("DOMContentLoaded", async () => {
  fillMainInput(getState(STORAGE_KEYS.mainInput, null));
  setupRefreshNotice(
    [STORAGE_KEYS.compareList, STORAGE_KEYS.selectedMajors, STORAGE_KEYS.recommendResult],
    async () => {
      fillMainInput(getState(STORAGE_KEYS.mainInput, null));
    }
  );
  $("chatResult").classList.add("hidden");
  loadDataScope();
  $("formattedMockText").value = getState("vrs.mockFormatted", "");
  $("mockAnalyzeResult").textContent = getState("vrs.mockAnalysis", "");
  $("formattedMockText").addEventListener("input", () => setState("vrs.mockFormatted", $("formattedMockText").value));
  renderMockExams();
  $("openRecommendBtn").addEventListener("click", openRecommendPage);
  $("openMajorsBtn").addEventListener("click", openMajorsPage);
  $("askBtn").addEventListener("click", askCloud);
  $("addTextRecordBtn").addEventListener("click", () => { addTextRecord(); });
  $("formatMockBtn").addEventListener("click", formatMockExams);
  $("analyzeMockBtn").addEventListener("click", analyzeMockExams);
  let saveTimer;
  ["score", "rank", "year", "subjectCombo", "majors", "provinces", "targets", "rankWindow", "candidateScope", "targetCount", "ratio", "extraNote"].forEach((id) => {
    $(id).addEventListener("input", () => {
      clearTimeout(saveTimer);
      $("draftStatus").textContent = "正在保存…";
      saveTimer = setTimeout(saveDraft, 400);
    });
  });
  const updateScope = () => { $("rankWindow").disabled = $("candidateScope").value !== "window"; };
  $("candidateScope").addEventListener("change", updateScope);
  updateScope();
  window.addEventListener("pagehide", () => { clearTimeout(saveTimer); saveDraft(); });
  $("question").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !$("askBtn").disabled) askCloud();
  });
});

async function loadDataScope() {
  try {
    const data = await api("/api/v1/data/scope");
    const dataset = data.dataset || {};
    if (dataset.import_status !== "ready" || !data.years.length) {
      $("dataScopeStatus").textContent = "浙江图谱正在重建，完成后刷新即可生成推荐。";
      $("openRecommendBtn").disabled = true;
      return;
    }
    const savedYear = $("year").value;
    $("year").replaceChildren(...data.years.map((row) => {
      const option = document.createElement("option");
      option.value = row.year; option.textContent = `${row.year} 年 · ${row.rank_count.toLocaleString()} 条位次记录`;
      return option;
    }));
    if (data.years.some((row) => String(row.year) === savedYear)) $("year").value = savedYear;
    $("dataScopeStatus").textContent = `数据范围：浙江生源 · ${dataset.first_year}–${dataset.last_year} 年 · ${dataset.offer_count.toLocaleString()} 条原始录取事实`;
  } catch (err) { $("dataScopeStatus").textContent = "数据范围读取失败：" + err.message; }
}
