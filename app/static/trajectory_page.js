const $ = (id) => document.getElementById(id);
const MOCK_EXAM_KEY = "vrs.mockExams";

function getMockExams() {
  return getState(MOCK_EXAM_KEY, []);
}

function setMockExams(records) {
  const saved = setState(MOCK_EXAM_KEY, records);
  if (saved) renderTrajectory();
  return saved;
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
  if (!records.length) return;
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
    const data = await api("/api/v1/mock-exams/format", "POST", { records: normalized });
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
    const data = await api("/api/v1/mock-exams/analyze", "POST", { formatted_text });
    $("mockAnalyzeResult").textContent = data.analysis?.answer || "";
    setState("vrs.mockAnalysis", $("mockAnalyzeResult").textContent);
    showToast("分析完成", "success");
  } catch(err) {
    showToast("分析失败: " + (err.message || String(err)), "error");
  }
  btn.disabled = false;
  btn.textContent = "优势专业 / 领域分析（云端）";
}

// ── Score Trajectory Prediction ──
function parseScoreFromText(text) {
  if (!text) return null;
  const patterns = [
    /总分\s*[：:]?\s*(\d{1,3}(?:\.\d+)?)(?!\d)/,
    /总成绩\s*[：:]?\s*(\d{1,3}(?:\.\d+)?)(?!\d)/,
    /score\s*[：:]\s*(\d{1,3}(?:\.\d+)?)(?!\d)/i,
    /^\s*(\d{1,3}(?:\.\d+)?)\s*分?\s*$/,
  ];
  for (const p of patterns) {
    const m = text.match(p);
    if (m) {
      const value = Number(m[1]);
      if (value >= 0 && value <= 750) return value;
    }
  }
  return null;
}

function extractScoresFromMockExams() {
  const records = getMockExams();
  const scores = [];
  for (const rec of records) {
    const text = (rec.raw_text || "") + "\n" + (rec.ocr_text || "");
    const score = parseScoreFromText(text);
    if (score !== null) {
      scores.push({
        id: rec.id,
        score: score,
        label: rec.id.replace("mock_", "第").replace(/_/g, "-") + "次",
      });
    }
  }
  return scores;
}

function linearRegression(points) {
  const n = points.length;
  if (n < 2) return null;
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (let i = 0; i < n; i++) {
    sumX += i;
    sumY += points[i];
    sumXY += i * points[i];
    sumX2 += i * i;
  }
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  let ssRes = 0, ssTot = 0;
  const meanY = sumY / n;
  for (let i = 0; i < n; i++) {
    ssRes += Math.pow(points[i] - (slope * i + intercept), 2);
    ssTot += Math.pow(points[i] - meanY, 2);
  }
  const r2 = ssTot > 0 ? 1 - ssRes / ssTot : 0;
  return { slope, intercept, r2 };
}

function renderTrajectory() {
  const scores = extractScoresFromMockExams();
  const emptyEl = $("trajectoryEmpty");
  const chartDom = $("trajectoryChart");
  const summaryEl = $("trajectorySummary");

  if (scores.length < 2) {
    if (emptyEl) emptyEl.classList.remove("hidden");
    if (chartDom) chartDom.classList.add("hidden");
    if (summaryEl) summaryEl.style.display = "none";
    return;
  }

  if (emptyEl) emptyEl.classList.add("hidden");
  if (chartDom) chartDom.classList.remove("hidden");

  const values = scores.map((s) => s.score);
  const labels = scores.map((s) => s.label);
  const reg = linearRegression(values);

  const predictions = [];
  let predSummary = "";
  if (reg) {
    const nextIdx = values.length;
    const pred1 = Math.round(Math.min(750, Math.max(200, reg.slope * nextIdx + reg.intercept)));
    const pred2 = Math.round(Math.min(750, Math.max(200, reg.slope * (nextIdx + 1) + reg.intercept)));
    predictions.push({ label: "预测+1", value: pred1 });
    predictions.push({ label: "预测+2", value: pred2 });
    const trend = reg.slope > 1 ? "上升" : reg.slope < -1 ? "下降" : "稳定";
    predSummary =
      `趋势：${trend}（斜率 ${reg.slope.toFixed(2)} 分/次）| R²=${reg.r2.toFixed(2)} | ` +
      `预测下次: ${pred1}分 | 预测下下次: ${pred2}分`;
    if (summaryEl) {
      summaryEl.style.display = "";
      summaryEl.textContent = predSummary;
    }
  }

  if (!window.echarts) { if (summaryEl) summaryEl.textContent += "（图表组件加载失败，请检查网络后刷新）"; return; }
  const existing = echarts.getInstanceByDom(chartDom);
  if (existing) existing.dispose();
  const chart = echarts.init(chartDom, getEChartsTheme());

  const xLabels = [...labels, ...predictions.map((p) => p.label)];
  const actualData = [...values, ...predictions.map(() => null)];
  const predData = [...values.map(() => null), ...predictions.map((p) => p.value)];

  if (values.length > 0 && predictions.length > 0) {
    predData[values.length - 1] = values[values.length - 1];
  }

  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["实际分数", "预测分数"], bottom: 0, textStyle: { color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-secondary").trim() || "#94a3b8" } },
    xAxis: { type: "category", data: xLabels, axisLabel: { color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-muted").trim() || "#94a3b8" } },
    yAxis: { type: "value", name: "分数", min: function(v) { return Math.max(0, v.min - 30); }, max: 750, axisLabel: { color: getComputedStyle(document.documentElement).getPropertyValue("--color-text-muted").trim() || "#94a3b8" } },
    series: [
      { name: "实际分数", type: "line", data: actualData, smooth: true, lineStyle: { color: "#1E40AF", width: 2.5 }, itemStyle: { color: "#1E40AF" }, symbol: "circle", symbolSize: 8, markLine: reg ? { silent: true, data: [{ type: "average", name: "平均" }], lineStyle: { color: "#94A3B8", type: "dashed" } } : undefined },
      { name: "预测分数", type: "line", data: predData, smooth: true, lineStyle: { color: "#D97706", width: 2, type: "dashed" }, itemStyle: { color: "#D97706" }, symbol: "diamond", symbolSize: 10, areaStyle: { color: "rgba(217, 119, 6, 0.08)" } },
    ],
    grid: { top: 20, left: 50, right: 20, bottom: 40 },
    backgroundColor: "transparent",
  });
}

window.addEventListener("DOMContentLoaded", () => {
  setupRefreshNotice(
    [STORAGE_KEYS.compareList, STORAGE_KEYS.selectedMajors, STORAGE_KEYS.recommendResult],
    () => { renderMockExams(); renderTrajectory(); }
  );
  $("formattedMockText").value = getState("vrs.mockFormatted", "");
  $("mockAnalyzeResult").textContent = getState("vrs.mockAnalysis", "");
  $("formattedMockText").addEventListener("input", () => setState("vrs.mockFormatted", $("formattedMockText").value));
  renderMockExams();
  renderTrajectory();
  $("addTextRecordBtn").addEventListener("click", () => { addTextRecord(); setTimeout(renderTrajectory, 500); });
  $("formatMockBtn").addEventListener("click", formatMockExams);
  $("analyzeMockBtn").addEventListener("click", analyzeMockExams);
  $("refreshTrajectoryBtn").addEventListener("click", renderTrajectory);

  window.addEventListener("storage", (e) => {
    if (e.key === MOCK_EXAM_KEY) { renderMockExams(); setTimeout(renderTrajectory, 300); }
  });
});
