import { dom } from "./dom.js";
import { getOutputNameForBatch } from "./naming.js";
import {
  getActiveBatch,
  getBatchIndex,
  getRunnableEntries,
  getTotalBytes,
  getTotalFiles,
  state,
} from "./state.js";
import { formatBytes } from "./utils.js";

export function showStatus(message, showProgress = true) {
  dom.statusPanel.hidden = false;
  dom.statusText.textContent = message;
  dom.progressBar.style.width = showProgress ? "0%" : "100%";
}

export function updateProgress(percent, message) {
  dom.statusPanel.hidden = false;
  dom.progressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  if (message) {
    dom.statusText.textContent = message;
  }
}

export function clearStatus() {
  dom.statusPanel.hidden = true;
  dom.statusText.textContent = "";
  dom.progressBar.style.width = "0%";
}

function renderTabs(config, actions) {
  dom.batchTabs.innerHTML = "";

  state.batches.forEach((batch, index) => {
    const tab = dom.batchTabTemplate.content.firstElementChild.cloneNode(true);
    const isActive = batch.id === state.activeBatchId;
    const outputName = getOutputNameForBatch(batch, index, config);

    tab.dataset.id = batch.id;
    tab.setAttribute("aria-selected", String(isActive));
    tab.tabIndex = isActive ? 0 : -1;
    tab.classList.toggle("is-active", isActive);
    tab.querySelector(".batch-tab-title").textContent = `Batch ${index + 1}`;
    tab.querySelector(".batch-tab-meta").textContent = `${batch.items.length} files / ${outputName}`;
    tab.addEventListener("click", () => actions.selectBatch(batch.id));
    dom.batchTabs.appendChild(tab);
  });
}

function renderNameControls(config) {
  const batch = getActiveBatch();
  const activeIndex = getBatchIndex(batch.id);
  const isSequence = config.mode === "sequence";

  dom.sequenceControl.hidden = !isSequence;
  dom.customNameControl.hidden = isSequence;
  dom.generatedNameControl.hidden = !isSequence;

  if (document.activeElement !== dom.batchNameInput) {
    dom.batchNameInput.value = batch.filename;
  }
  if (document.activeElement !== dom.sequenceStart && !dom.sequenceStart.value.trim()) {
    dom.sequenceStart.value = "Section1";
  }

  dom.generatedNamePreview.textContent = getOutputNameForBatch(batch, activeIndex, config);
}

function renderActiveBatch(config, actions) {
  const batch = getActiveBatch();
  const activeIndex = getBatchIndex(batch.id);
  const outputName = getOutputNameForBatch(batch, activeIndex, config);

  dom.dropZoneTitle.textContent = `Add MP3s to Batch ${activeIndex + 1}`;
  dom.dropZoneHint.textContent = `${outputName} will be included in ${dom.archiveNameInput.value || "mp3-batches.zip"}.`;
  dom.activeBatchTitle.textContent = `Batch ${activeIndex + 1}`;
  dom.activeBatchMeta.textContent = `${batch.items.length} files / ${outputName}`;

  dom.fileList.innerHTML = "";
  batch.items.forEach((item, index) => {
    const node = dom.fileItemTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;
    node.querySelector(".file-name").textContent = item.file.name;
    node.querySelector(".file-meta").textContent = `${index + 1} of ${batch.items.length} / ${formatBytes(item.file.size)}`;

    node.querySelector(".move-up").disabled = state.isBusy || index === 0;
    node.querySelector(".move-down").disabled = state.isBusy || index === batch.items.length - 1;
    node.querySelector(".remove").disabled = state.isBusy;
    node.querySelector(".move-up").addEventListener("click", () => actions.moveItem(index, index - 1));
    node.querySelector(".move-down").addEventListener("click", () => actions.moveItem(index, index + 1));
    node.querySelector(".remove").addEventListener("click", () => actions.removeItem(index));

    node.draggable = !state.isBusy;
    node.addEventListener("dragstart", event => {
      if (state.isBusy) return;
      state.dragSourceId = item.id;
      node.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.id);
    });

    node.addEventListener("dragend", () => {
      state.dragSourceId = null;
      node.classList.remove("dragging");
    });

    node.addEventListener("dragover", event => {
      if (state.isBusy) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });

    node.addEventListener("drop", event => {
      if (state.isBusy) return;
      event.preventDefault();
      const sourceId = state.dragSourceId || event.dataTransfer.getData("text/plain");
      const fromIndex = batch.items.findIndex(candidate => candidate.id === sourceId);
      const toIndex = batch.items.findIndex(candidate => candidate.id === item.id);
      actions.moveItem(fromIndex, toIndex);
    });

    dom.fileList.appendChild(node);
  });

  dom.emptyMessage.hidden = batch.items.length > 0;
}

function renderSummary() {
  const totalFiles = getTotalFiles();
  const readyCount = getRunnableEntries().length;
  dom.batchSummary.textContent = `${state.batches.length} batch${state.batches.length === 1 ? "" : "es"}`;
  dom.readySummary.textContent = `${readyCount} ready`;
  dom.fileCount.textContent = `${totalFiles} file${totalFiles === 1 ? "" : "s"}`;
  dom.totalSize.textContent = formatBytes(getTotalBytes());
}

function renderControlStates() {
  const activeBatch = getActiveBatch();
  const totalFiles = getTotalFiles();
  const hasRunnableBatch = getRunnableEntries().length > 0;

  dom.fileInput.disabled = state.isBusy;
  dom.selectButton.disabled = state.isBusy;
  dom.addBatchButton.disabled = state.isBusy;
  dom.removeBatchButton.disabled = state.isBusy || state.batches.length <= 1;
  dom.clearBatchButton.disabled = state.isBusy || activeBatch.items.length === 0;
  dom.clearAllButton.disabled = state.isBusy || (state.batches.length === 1 && totalFiles === 0);
  dom.mergeButton.disabled = state.isBusy || !hasRunnableBatch;
  dom.namingMode.disabled = state.isBusy;
  dom.sequenceStart.disabled = state.isBusy || dom.namingMode.value !== "sequence";
  dom.archiveNameInput.disabled = state.isBusy;
  dom.batchNameInput.disabled = state.isBusy || dom.namingMode.value !== "custom";
  dom.dropZone.classList.toggle("is-busy", state.isBusy);
}

export function render(config, actions) {
  renderTabs(config, actions);
  renderNameControls(config);
  renderActiveBatch(config, actions);
  renderSummary();
  renderControlStates();
}
