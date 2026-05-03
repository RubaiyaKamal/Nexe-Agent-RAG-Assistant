/**
 * RAG Assistant — Frontend Application
 * Communicates with the FastAPI backend at http://localhost:8000
 */
const API_BASE = "https://nexe-agent-rag-assistant-production.up.railway.app/"
const API_URL = "https://your-actual-railway-url.up.railway.app";

// ============================================================
// State
// ============================================================
const state = {
  documents: [],        // [{doc_id, filename, chunk_count}]
  isQuerying: false,
  isUploading: false,
};

// ============================================================
// DOM references
// ============================================================
const $ = (id) => document.getElementById(id);

const dropZone     = $("dropZone");
const fileInput    = $("fileInput");
const docList      = $("docList");
const docCount     = $("docCount");
const chunkCount   = $("chunkCount");
const chatMessages = $("chatMessages");
const questionInput= $("questionInput");
const sendBtn      = $("sendBtn");
const statusDot    = $("statusDot");
const statusText   = $("statusText");
const uploadProgress = $("uploadProgress");
const progressBar  = $("progressBar");
const progressLabel= $("progressLabel");
const toastContainer = $("toastContainer");

// ============================================================
// Initialise
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  refreshDocuments();
  attachEventListeners();
  scheduleHealthCheck();
});

// ============================================================
// Event listeners
// ============================================================
function attachEventListeners() {
  // Drop zone
  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("drag-over");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const files = Array.from(e.dataTransfer.files);
    if (files.length) handleFileUpload(files[0]);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) handleFileUpload(fileInput.files[0]);
    fileInput.value = "";
  });

  // Question input — submit on Enter (Shift+Enter = newline)
  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitQuestion();
    }
  });

  // Auto-resize textarea
  questionInput.addEventListener("input", () => {
    questionInput.style.height = "auto";
    questionInput.style.height = Math.min(questionInput.scrollHeight, 140) + "px";
  });

  sendBtn.addEventListener("click", submitQuestion);
}

// ============================================================
// Health check
// ============================================================
async function scheduleHealthCheck() {
  await checkHealth();
  setInterval(checkHealth, 30_000);
}

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const data = await res.json();
      setOnline(true);
      updateStats(data.documents ?? 0, data.chunks ?? 0);
    } else {
      setOnline(false);
    }
  } catch {
    setOnline(false);
  }
}

function setOnline(online) {
  statusDot.className = "status-dot " + (online ? "online" : "error");
  statusText.textContent = online ? "API Online" : "API Offline";
}

// ============================================================
// Upload
// ============================================================
async function handleFileUpload(file) {
  const allowed = [".pdf", ".txt", ".docx"];
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!allowed.includes(ext)) {
    showToast(`Unsupported file type: ${ext}. Allowed: PDF, TXT, DOCX`, "error");
    return;
  }

  if (state.isUploading) {
    showToast("Another upload is in progress…", "info");
    return;
  }

  state.isUploading = true;
  showUploadProgress(true, `Uploading ${file.name}…`);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || `Upload failed (${res.status})`);
    }

    showToast(`✓ "${data.filename}" indexed — ${data.chunks} chunks`, "success");
    await refreshDocuments();
  } catch (err) {
    showToast(`Upload error: ${err.message}`, "error");
  } finally {
    state.isUploading = false;
    showUploadProgress(false);
  }
}

function showUploadProgress(visible, label = "") {
  uploadProgress.style.display = visible ? "block" : "none";
  if (visible) {
    progressBar.style.width = "0%";
    progressLabel.textContent = label;
    // Fake progress animation since XHR isn't used
    let pct = 0;
    const interval = setInterval(() => {
      pct = Math.min(pct + Math.random() * 15, 90);
      progressBar.style.width = pct + "%";
      if (!state.isUploading) {
        progressBar.style.width = "100%";
        clearInterval(interval);
      }
    }, 200);
  }
}

// ============================================================
// Documents
// ============================================================
async function refreshDocuments() {
  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) return;
    const docs = await res.json();
    state.documents = docs;
    renderDocList(docs);
    const totalChunks = docs.reduce((s, d) => s + d.chunk_count, 0);
    updateStats(docs.length, totalChunks);
  } catch {
    // Silently ignore if API is offline
  }
}

function renderDocList(docs) {
  docList.innerHTML = "";

  if (!docs.length) return;

  docs.forEach((doc) => {
    const icon = fileIcon(doc.filename);
    const item = document.createElement("div");
    item.className = "doc-item";
    item.innerHTML = `
      <span class="doc-icon">${icon}</span>
      <div class="doc-info">
        <div class="doc-name" title="${escHtml(doc.filename)}">${escHtml(doc.filename)}</div>
        <div class="doc-meta">${doc.chunk_count} chunk${doc.chunk_count !== 1 ? "s" : ""}</div>
      </div>
      <button class="doc-delete" title="Remove document" onclick="deleteDocument('${doc.doc_id}', this)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"/>
          <path d="M19 6l-1 14H6L5 6"/>
          <path d="M10 11v6M14 11v6"/>
          <path d="M9 6V4h6v2"/>
        </svg>
      </button>
    `;
    docList.appendChild(item);
  });
}

async function deleteDocument(docId, btnEl) {
  btnEl.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/documents/${docId}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Delete failed");
    showToast(`Document removed (${data.chunks_deleted} chunks deleted)`, "success");
    await refreshDocuments();
  } catch (err) {
    showToast(`Delete error: ${err.message}`, "error");
    btnEl.disabled = false;
  }
}

function updateStats(docs, chunks) {
  docCount.textContent  = docs;
  chunkCount.textContent = chunks;
}

// ============================================================
// Chat
// ============================================================
function clearChat() {
  chatMessages.innerHTML = `
    <div class="chat-welcome" id="chatWelcome">
      <div class="chat-welcome-icon">💬</div>
      <div class="chat-welcome-text">Upload documents and ask questions. The assistant will answer using only the content in your uploaded files.</div>
    </div>`;
}

async function submitQuestion() {
  const question = questionInput.value.trim();
  if (!question || state.isQuerying) return;

  // Clear welcome state
  const welcome = $("chatWelcome");
  if (welcome) welcome.remove();

  // Append user message
  appendMessage("user", question);

  questionInput.value = "";
  questionInput.style.height = "auto";

  // Thinking indicator
  const thinkingId = appendThinking();

  state.isQuerying = true;
  sendBtn.disabled = true;
  questionInput.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    const data = await res.json();
    removeThinking(thinkingId);

    if (!res.ok) {
      throw new Error(data.detail || `Query failed (${res.status})`);
    }

    appendMessage("assistant", data.answer, data.sources || []);
  } catch (err) {
    removeThinking(thinkingId);
    appendMessage("assistant", `⚠ Error: ${err.message}`, []);
  } finally {
    state.isQuerying = false;
    sendBtn.disabled = false;
    questionInput.disabled = false;
    questionInput.focus();
  }
}

function appendMessage(role, text, sources = []) {
  const msg = document.createElement("div");
  msg.className = `message ${role}`;

  const avatar = role === "user" ? "👤" : "🤖";

  let sourcesHtml = "";
  if (sources.length) {
    const sourceItems = sources.map((s, i) => `
      <div class="source-item">
        <div class="source-meta">
          <span>📄 ${escHtml(s.filename || s.doc_id)}</span>
          <span>chunk ${s.chunk_index}</span>
          <span>score ${(1 - s.distance).toFixed(3)}</span>
        </div>
        <div class="source-text">${escHtml(s.text.substring(0, 220))}${s.text.length > 220 ? "…" : ""}</div>
      </div>`).join("");

    sourcesHtml = `
      <button class="sources-toggle" onclick="toggleSources(this)">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
        ${sources.length} source${sources.length !== 1 ? "s" : ""}
      </button>
      <div class="sources-list" style="display:none">${sourceItems}</div>`;
  }

  msg.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-body">
      <div class="message-role">${role === "user" ? "You" : "Assistant"}</div>
      <div class="message-text">${formatText(text)}</div>
      ${sourcesHtml}
    </div>`;

  chatMessages.appendChild(msg);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function toggleSources(btn) {
  const list = btn.nextElementSibling;
  const open = list.style.display !== "none";
  list.style.display = open ? "none" : "flex";
  const arrow = btn.querySelector("svg polyline");
  if (arrow) {
    arrow.setAttribute("points", open ? "6 9 12 15 18 9" : "6 15 12 9 18 15");
  }
}

let _thinkingCounter = 0;
function appendThinking() {
  const id = `thinking-${++_thinkingCounter}`;
  const el = document.createElement("div");
  el.className = "message assistant";
  el.id = id;
  el.innerHTML = `
    <div class="message-avatar">🤖</div>
    <div class="message-body">
      <div class="message-role">Assistant</div>
      <div class="message-text">
        <div class="thinking-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>`;
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return id;
}

function removeThinking(id) {
  const el = $(id);
  if (el) el.remove();
}

// ============================================================
// Toasts
// ============================================================
function showToast(msg, type = "info", duration = 4000) {
  const icons = { success: "✓", error: "✕", info: "ℹ" };
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || ""}</span><span>${escHtml(String(msg))}</span>`;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(30px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ============================================================
// Utilities
// ============================================================
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatText(text) {
  // Very light markdown: **bold**, `code`, newlines
  return escHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code style='font-family:var(--mono);background:var(--bg-primary);padding:1px 4px;border-radius:3px;font-size:0.85em'>$1</code>")
    .replace(/\n/g, "<br>");
}

function fileIcon(filename) {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  if (ext === ".pdf")  return "📕";
  if (ext === ".docx") return "📘";
  if (ext === ".txt")  return "📄";
  return "📎";
}
