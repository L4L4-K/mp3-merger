const dropZone = document.querySelector("#dropZone");
const fileInput = document.querySelector("#fileInput");
const selectButton = document.querySelector("#selectButton");
const clearButton = document.querySelector("#clearButton");
const mergeButton = document.querySelector("#mergeButton");
const fileList = document.querySelector("#fileList");
const emptyMessage = document.querySelector("#emptyMessage");
const fileCount = document.querySelector("#fileCount");
const totalSize = document.querySelector("#totalSize");
const statusPanel = document.querySelector("#statusPanel");
const statusText = document.querySelector("#statusText");
const progressBar = document.querySelector("#progressBar");
const template = document.querySelector("#fileItemTemplate");

let items = [];
let dragSourceId = null;

function createId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function isMp3(file) {
  const type = (file.type || "").toLowerCase();
  return file.name.toLowerCase().endsWith(".mp3") || type === "audio/mpeg" || type === "audio/mp3";
}

function addFiles(fileListLike) {
  const files = Array.from(fileListLike || []);
  const rejected = [];

  for (const file of files) {
    if (!isMp3(file)) {
      rejected.push(file.name);
      continue;
    }
    items.push({ id: createId(), file });
  }

  render();

  if (rejected.length > 0) {
    showStatus(`MP3 以外のファイルを除外しました:\n${rejected.join("\n")}`, false);
  }
}

function moveItem(fromIndex, toIndex) {
  if (toIndex < 0 || toIndex >= items.length || fromIndex === toIndex) return;
  const [item] = items.splice(fromIndex, 1);
  items.splice(toIndex, 0, item);
  render();
}

function removeItem(index) {
  items.splice(index, 1);
  render();
}

function setBusy(isBusy) {
  mergeButton.disabled = isBusy || items.length < 2;
  clearButton.disabled = isBusy || items.length === 0;
  selectButton.disabled = isBusy;
  dropZone.classList.toggle("is-busy", isBusy);
}

function showStatus(message, showProgress = true) {
  statusPanel.hidden = false;
  statusText.textContent = message;
  progressBar.style.width = showProgress ? "0%" : "100%";
}

function clearStatus() {
  statusPanel.hidden = true;
  statusText.textContent = "";
  progressBar.style.width = "0%";
}

function render() {
  fileList.innerHTML = "";

  items.forEach((item, index) => {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;
    node.querySelector(".file-name").textContent = item.file.name;
    node.querySelector(".file-meta").textContent = `${index + 1} 番目 / ${formatBytes(item.file.size)}`;

    node.querySelector(".move-up").disabled = index === 0;
    node.querySelector(".move-down").disabled = index === items.length - 1;
    node.querySelector(".move-up").addEventListener("click", () => moveItem(index, index - 1));
    node.querySelector(".move-down").addEventListener("click", () => moveItem(index, index + 1));
    node.querySelector(".remove").addEventListener("click", () => removeItem(index));

    node.addEventListener("dragstart", event => {
      dragSourceId = item.id;
      node.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.id);
    });

    node.addEventListener("dragend", () => {
      dragSourceId = null;
      node.classList.remove("dragging");
    });

    node.addEventListener("dragover", event => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });

    node.addEventListener("drop", event => {
      event.preventDefault();
      const sourceId = dragSourceId || event.dataTransfer.getData("text/plain");
      const fromIndex = items.findIndex(candidate => candidate.id === sourceId);
      const toIndex = items.findIndex(candidate => candidate.id === item.id);
      moveItem(fromIndex, toIndex);
    });

    fileList.appendChild(node);
  });

  const total = items.reduce((sum, item) => sum + item.file.size, 0);
  fileCount.textContent = `${items.length} ファイル`;
  totalSize.textContent = formatBytes(total);
  emptyMessage.hidden = items.length > 0;
  mergeButton.disabled = items.length < 2;
  clearButton.disabled = items.length === 0;

  if (items.length === 0) {
    clearStatus();
  }
}

function extractErrorMessage(xhr) {
  const contentType = xhr.getResponseHeader("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      const body = JSON.parse(xhr.responseText);
      return body.detail || xhr.statusText || "エラーが発生しました。";
    } catch {
      return xhr.statusText || "エラーが発生しました。";
    }
  }
  return xhr.responseText || xhr.statusText || "エラーが発生しました。";
}

function mergeFiles() {
  if (items.length < 2) return;

  const formData = new FormData();
  items.forEach(item => formData.append("files", item.file, item.file.name));

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/merge");
  xhr.responseType = "blob";

  setBusy(true);
  showStatus("アップロード中です。", true);

  xhr.upload.addEventListener("progress", event => {
    if (event.lengthComputable) {
      const percent = Math.round((event.loaded / event.total) * 85);
      progressBar.style.width = `${percent}%`;
      statusText.textContent = `アップロード中です。${percent}%`;
    }
  });

  xhr.addEventListener("load", () => {
    setBusy(false);

    if (xhr.status >= 200 && xhr.status < 300) {
      progressBar.style.width = "100%";
      statusText.textContent = "結合が完了しました。ダウンロードを開始します。";

      const blob = xhr.response;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "merged.mp3";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return;
    }

    if (xhr.response instanceof Blob) {
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const body = JSON.parse(reader.result);
          showStatus(body.detail || "結合に失敗しました。", false);
        } catch {
          showStatus("結合に失敗しました。", false);
        }
      };
      reader.readAsText(xhr.response);
    } else {
      showStatus(extractErrorMessage(xhr), false);
    }
  });

  xhr.addEventListener("error", () => {
    setBusy(false);
    showStatus("通信に失敗しました。サーバーが起動しているか確認してください。", false);
  });

  xhr.send(formData);
}

dropZone.addEventListener("click", event => {
  if (event.target === selectButton) return;
  fileInput.click();
});

selectButton.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", event => {
  addFiles(event.target.files);
  fileInput.value = "";
});

["dragenter", "dragover"].forEach(name => {
  dropZone.addEventListener(name, event => {
    event.preventDefault();
    dropZone.classList.add("is-over");
  });
});

["dragleave", "drop"].forEach(name => {
  dropZone.addEventListener(name, event => {
    event.preventDefault();
    dropZone.classList.remove("is-over");
  });
});

dropZone.addEventListener("drop", event => addFiles(event.dataTransfer.files));

dropZone.addEventListener("keydown", event => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

clearButton.addEventListener("click", () => {
  items = [];
  render();
});

mergeButton.addEventListener("click", mergeFiles);

render();
