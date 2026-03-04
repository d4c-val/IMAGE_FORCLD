const previewBtn = document.getElementById("previewBtn");
const approveBtn = document.getElementById("approveBtn");
const regenerateRefsBtn = document.getElementById("regenerateRefsBtn");
const uploadBtn = document.getElementById("uploadBtn");
const storyTextEl = document.getElementById("storyText");
const styleHintEl = document.getElementById("styleHint");
const referenceModeEl = document.getElementById("referenceMode");
const referenceFileEl = document.getElementById("referenceFile");
const uploadReferenceStrategyEl = document.getElementById("uploadReferenceStrategy");
const uploadHintEl = document.getElementById("uploadHint");
const progressBarEl = document.getElementById("progressBar");
const statusEl = document.getElementById("status");
const storyboardsEl = document.getElementById("storyboards");
const referenceCandidatesEl = document.getElementById("referenceCandidates");
const downloadResultBtn = document.getElementById("downloadResultBtn");
const downloadZipBtn = document.getElementById("downloadZipBtn");
const uploadBlockEl = document.getElementById("uploadBlock");
const galleryEl = document.getElementById("gallery");

let uploadedReferenceUrl = "";
let pollTimer = null;
let currentJobId = "";
let selectedReferenceIndex = null;
let currentStoryboards = [];
let latestJobData = null;

function setStatus(text, type = "info") {
  statusEl.textContent = text;
  statusEl.className = ""; // Reset classes
  if (type === "error") statusEl.classList.add("status-error");
  if (type === "success") statusEl.classList.add("status-success");
}

function setProgress(percent, isActive = false) {
  progressBarEl.style.width = `${Math.max(0, Math.min(100, percent || 0))}%`;
  if (isActive) {
    progressBarEl.classList.add("active");
  } else {
    progressBarEl.classList.remove("active");
  }
}

function renderStoryboards(storyboards) {
  currentStoryboards = storyboards || [];
  storyboardsEl.innerHTML = "";
  currentStoryboards.forEach((item) => {
    const card = document.createElement("article");
    card.className = "card storyboard-card";
    card.innerHTML = `
      <h3>分镜 #${item.shot_id}</h3>
      <label>标题</label>
      <input type="text" data-field="title" data-shot="${item.shot_id}" value="${escapeHtml(item.title || "")}" />
      <label>画面描述</label>
      <textarea rows="4" data-field="scene_description" data-shot="${item.shot_id}">${escapeHtml(item.scene_description || "")}</textarea>
      <label>镜头语言</label>
      <input type="text" data-field="camera_language" data-shot="${item.shot_id}" value="${escapeHtml(item.camera_language || "")}" />
      <label>氛围</label>
      <input type="text" data-field="mood" data-shot="${item.shot_id}" value="${escapeHtml(item.mood || "")}" />
    `;
    storyboardsEl.appendChild(card);
  });
}

function renderOutputs(outputs) {
  galleryEl.innerHTML = "";
  outputs.forEach((item) => {
    const card = document.createElement("article");
    card.className = "card";

    const title = document.createElement("h3");
    title.textContent = `#${item.shot_id} ${item.title}`;
    card.appendChild(title);

    const modelTag = document.createElement("p");
    modelTag.className = "muted";
    modelTag.textContent = item.uses_edit_model
      ? "模型：qwen-image-edit-max（人物一致性）"
      : "模型：qwen-image（普通生成）";
    card.appendChild(modelTag);

    const prompt = document.createElement("p");
    prompt.className = "prompt";
    prompt.textContent = item.prompt || "";
    card.appendChild(prompt);

    const imageSrc = item.web_url;
    if (imageSrc) {
      const img = document.createElement("img");
      img.src = imageSrc;
      img.alt = item.title;
      img.classList.add("zoomable");
      img.addEventListener("click", () => openModal(imageSrc, item.prompt));
      card.appendChild(img);

      const saveLink = document.createElement("a");
      saveLink.href = imageSrc;
      saveLink.download = `shot_${String(item.shot_id).padStart(2, "0")}.png`;
      saveLink.textContent = "保存该分镜图片";
      card.appendChild(saveLink);
    } else {
      const note = document.createElement("p");
      note.textContent = "该分镜未获取到本地图片，请查看后端日志。";
      card.appendChild(note);
    }
    galleryEl.appendChild(card);
  });
}

function renderReferenceCandidates(candidates) {
  referenceCandidatesEl.innerHTML = "";
  const list = Array.isArray(candidates) ? candidates : [];
  list.forEach((item) => {
    const card = document.createElement("article");
    card.className = `card ref-card ${selectedReferenceIndex === item.index ? "active" : ""}`;
    card.dataset.index = item.index;
    card.innerHTML = `
      <h3>参考图 ${item.index + 1}</h3>
      <p class="muted">${item.prompt || ""}</p>
      ${item.web_url ? `<img src="${item.web_url}" alt="参考图${item.index + 1}" class="zoomable" />` : "<p>该候选图生成失败</p>"}
    `;
    const imgEl = card.querySelector("img");
    if (imgEl) {
      imgEl.addEventListener("click", (e) => {
        e.stopPropagation(); // 防止触发卡片的选中事件
        openModal(item.web_url, item.prompt);
      });
    }
    card.addEventListener("click", () => {
      selectedReferenceIndex = item.index;
      renderReferenceCandidates(list);
      refreshApproveButton();
    });
    referenceCandidatesEl.appendChild(card);
  });
}

async function uploadReference() {
  const file = referenceFileEl.files && referenceFileEl.files[0];
  if (!file) {
    uploadHintEl.textContent = "请先选择图片文件。";
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  uploadBtn.disabled = true;
  uploadHintEl.textContent = "上传中...";
  try {
    const response = await fetch("/api/upload-reference", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      let errMsg = "上传失败";
      if (Array.isArray(data.detail)) errMsg = data.detail.map(e => e.msg).join('; ');
      else if (data.detail) errMsg = data.detail;
      throw new Error(errMsg);
    }
    uploadedReferenceUrl = data.reference_image_url;
    uploadHintEl.textContent = `上传成功：${uploadedReferenceUrl}`;
  } catch (error) {
    uploadHintEl.textContent = `上传失败：${error.message}`;
  } finally {
    uploadBtn.disabled = false;
  }
}

// Lightbox Modal Logic
const imageModal = document.getElementById("imageModal");
const modalImage = document.getElementById("modalImage");
const modalCaption = document.getElementById("modalCaption");
const closeModalBtn = document.getElementById("closeModal");

function openModal(imgSrc, captionText) {
  imageModal.style.display = "block";
  setTimeout(() => imageModal.classList.add("show"), 10);
  modalImage.src = imgSrc;
  modalCaption.textContent = captionText || "";
}

function closeModal() {
  imageModal.classList.remove("show");
  setTimeout(() => imageModal.style.display = "none", 300);
}

if (closeModalBtn) {
  closeModalBtn.addEventListener("click", closeModal);
}

window.addEventListener("click", (event) => {
  if (event.target === imageModal) {
    closeModal();
  }
});

async function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`);
    const data = await response.json();
    if (!response.ok) {
      let errMsg = "获取任务状态失败";
      if (Array.isArray(data.detail)) errMsg = data.detail.map(e => e.msg).join('; ');
      else if (data.detail) errMsg = data.detail;
      throw new Error(errMsg);
    }
      latestJobData = data;

      const isRunning = data.status === "running_preview" || data.status === "running_render" || data.status === "queued_preview" || data.status === "queued_render" || data.status === "queued";
      setProgress(data.progress || 0, isRunning);
      setStatus(`${data.message}（${data.progress || 0}%）`, "info");

      if (Array.isArray(data.storyboards) && data.storyboards.length > 0) {
        renderStoryboards(data.storyboards);
      }
      if (Array.isArray(data.reference_candidates) && data.reference_candidates.length > 0) {
        if (selectedReferenceIndex === null && Number.isInteger(data.selected_reference_index)) {
          selectedReferenceIndex = data.selected_reference_index;
        }
        renderReferenceCandidates(data.reference_candidates);
      }
      if (Array.isArray(data.outputs) && data.outputs.length > 0) {
        renderOutputs(data.outputs);
      }
      if (data.result_json_url) {
        downloadResultBtn.href = data.result_json_url;
      }
      if (data.images_zip_url) {
        downloadZipBtn.href = data.images_zip_url;
      }

      refreshApproveButton(data);

      if (data.status === "completed") {
        clearInterval(pollTimer);
        pollTimer = null;
        previewBtn.disabled = false;
        approveBtn.disabled = true;
        regenerateRefsBtn.disabled = true;
        setStatus("图片全部生成完成。", "success");
        setProgress(100, false);
      }
      if (data.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
        previewBtn.disabled = false;
        approveBtn.disabled = true;
        regenerateRefsBtn.disabled = true;
        setStatus(`生成失败：${data.message}`, "error");
        setProgress(data.progress || 0, false);
      }
    } catch (error) {
      clearInterval(pollTimer);
      pollTimer = null;
      previewBtn.disabled = false;
      approveBtn.disabled = true;
      regenerateRefsBtn.disabled = true;
      setStatus(`轮询失败：${error.message}`, "error");
      setProgress(0, false);
    }
  }, 1500);
}

async function startPreview() {
  const storyText = storyTextEl.value.trim();
  const styleHint = styleHintEl.value.trim();
  const referenceMode = referenceModeEl.value;
  if (!storyText) {
    setStatus("请先输入故事文本。", "error");
    return;
  }
  if (storyText.length < 30) {
    setStatus("故事文本太短了，请至少输入30个字符，以便AI能更好地理解情节。", "error");
    return;
  }
  if (referenceMode === "upload" && !uploadedReferenceUrl) {
    setStatus("你选择了上传参考图，请先上传一张图片。", "error");
    return;
  }

  setStatus("预览任务已提交，正在拆分分镜...", "info");
  setProgress(0, true);
  downloadResultBtn.href = "#";
  downloadZipBtn.href = "#";
  storyboardsEl.innerHTML = "";
  referenceCandidatesEl.innerHTML = "";
  galleryEl.innerHTML = "";
  selectedReferenceIndex = null;
  latestJobData = null;
  currentJobId = "";
  previewBtn.disabled = true;
  approveBtn.disabled = true;
  regenerateRefsBtn.disabled = true;
  try {
    const response = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        story_text: storyText,
        style_hint: styleHint,
        shot_count: 10,
        reference_mode: referenceMode,
        upload_reference_strategy: uploadReferenceStrategyEl.value,
        reference_image_url: referenceMode === "upload" ? uploadedReferenceUrl : null,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      let errMsg = "请求失败";
      if (Array.isArray(data.detail)) {
        errMsg = data.detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join('\n');
      } else if (data.detail) {
        errMsg = data.detail;
      }
      throw new Error(errMsg);
    }
    currentJobId = data.job_id;
    setStatus(`预览任务创建成功：${data.job_id}`);
    pollJob(currentJobId);
  } catch (error) {
    setStatus(`生成失败：${error.message}`, "error");
    previewBtn.disabled = false;
    regenerateRefsBtn.disabled = true;
    setProgress(0, false);
  }
}

function collectEditedStoryboards() {
  const cards = storyboardsEl.querySelectorAll(".storyboard-card");
  const list = [];
  cards.forEach((card, idx) => {
    const title = card.querySelector('[data-field="title"]').value.trim();
    const scene = card.querySelector('[data-field="scene_description"]').value.trim();
    const camera = card.querySelector('[data-field="camera_language"]').value.trim();
    const mood = card.querySelector('[data-field="mood"]').value.trim();
    list.push({
      shot_id: idx + 1,
      title,
      scene_description: scene,
      camera_language: camera,
      mood,
    });
  });
  return list;
}

function validateStoryboards(storyboards) {
  if (!Array.isArray(storyboards) || storyboards.length === 0) {
    return "没有可审核的分镜。";
  }
  for (const item of storyboards) {
    if (!item.title || !item.scene_description || !item.camera_language || !item.mood) {
      return `分镜 #${item.shot_id} 存在空字段，请补全后再继续。`;
    }
  }
  return "";
}

function refreshApproveButton(jobData = null) {
  const state = jobData || latestJobData;
  const canApprove =
    state &&
    state.status === "preview_ready" &&
    state.phase === "preview" &&
    Number.isInteger(selectedReferenceIndex);
  approveBtn.disabled = !canApprove;
  const canRegenerateRefs =
    state &&
    state.phase === "preview" &&
    state.status === "preview_ready" &&
    Boolean(currentJobId);
  regenerateRefsBtn.disabled = !canRegenerateRefs;
}

async function approveAndRender() {
  if (!currentJobId) {
    setStatus("请先生成分镜预览。", "error");
    return;
  }
  if (!Number.isInteger(selectedReferenceIndex)) {
    setStatus("请先选择一张参考图。", "error");
    return;
  }
  const storyboards = collectEditedStoryboards();
  const err = validateStoryboards(storyboards);
  if (err) {
    setStatus(err, "error");
    return;
  }

  approveBtn.disabled = true;
  previewBtn.disabled = true;
  setStatus("分镜已提交审核，开始生成图片...", "info");
  setProgress(25, true);
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        storyboards,
        selected_reference_index: selectedReferenceIndex,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      let errMsg = "审核提交失败";
      if (Array.isArray(data.detail)) errMsg = data.detail.map(e => e.msg).join('; ');
      else if (data.detail) errMsg = data.detail;
      throw new Error(errMsg);
    }
    setStatus(`审核通过，任务开始渲染：${data.job_id}`);
    pollJob(currentJobId);
  } catch (error) {
    approveBtn.disabled = false;
    previewBtn.disabled = false;
    setStatus(`审核失败：${error.message}`, "error");
    setProgress(0, false);
  }
}

async function regenerateReferences() {
  if (!currentJobId) {
    setStatus("请先生成分镜预览。", "error");
    return;
  }
  if (!latestJobData || latestJobData.phase !== "preview" || latestJobData.status !== "preview_ready") {
    setStatus("当前阶段不可重生参考图。", "error");
    return;
  }
  regenerateRefsBtn.disabled = true;
  approveBtn.disabled = true;
  setStatus("正在重新生成参考图，请稍候...", "info");
  setProgress(25, true);
  try {
    const response = await fetch(`/api/jobs/${currentJobId}/regenerate-references`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) {
      let errMsg = "重新生成参考图失败";
      if (Array.isArray(data.detail)) errMsg = data.detail.map(e => e.msg).join('; ');
      else if (data.detail) errMsg = data.detail;
      throw new Error(errMsg);
    }
    if (Array.isArray(data.reference_candidates)) {
      selectedReferenceIndex = Number.isInteger(data.selected_reference_index)
        ? data.selected_reference_index
        : null;
      renderReferenceCandidates(data.reference_candidates);
    }
    setStatus(data.message || "参考图已重新生成。", "success");
    setProgress(25, false);
    // 手动触发一次状态同步，避免界面按钮状态滞后
    const latestResp = await fetch(`/api/jobs/${currentJobId}`);
    const latestData = await latestResp.json();
    if (latestResp.ok) {
      latestJobData = latestData;
      refreshApproveButton(latestJobData);
    }
  } catch (error) {
    setStatus(`重生参考图失败：${error.message}`, "error");
    setProgress(25, false);
    refreshApproveButton();
  }
}

referenceModeEl.addEventListener("change", () => {
  const isUpload = referenceModeEl.value === "upload";
  uploadBlockEl.style.display = isUpload ? "block" : "none";
});

uploadBtn.addEventListener("click", uploadReference);
previewBtn.addEventListener("click", startPreview);
approveBtn.addEventListener("click", approveAndRender);
regenerateRefsBtn.addEventListener("click", regenerateReferences);

window.addEventListener("beforeunload", () => {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
});

(() => {
  const isUpload = referenceModeEl.value === "upload";
  uploadBlockEl.style.display = isUpload ? "block" : "none";
  setProgress(0);
  setStatus("等待输入故事并生成分镜预览...");
  regenerateRefsBtn.disabled = true;
  downloadResultBtn.href = "#";
  downloadZipBtn.href = "#";
  downloadResultBtn.addEventListener("click", (e) => {
    if (downloadResultBtn.getAttribute("href") === "#") {
      e.preventDefault();
      setStatus("当前没有可保存的结果文件。");
    }
  });
  downloadZipBtn.addEventListener("click", (e) => {
    if (downloadZipBtn.getAttribute("href") === "#") {
      e.preventDefault();
      setStatus("当前没有可下载的分镜ZIP。");
    }
  });
})();

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
