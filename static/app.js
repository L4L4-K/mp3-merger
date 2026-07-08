import { mergeBatches } from "./js/api.js";
import { dom } from "./js/dom.js";
import { findDuplicateOutputName, getOutputNameForBatch } from "./js/naming.js";
import { render, showStatus, updateProgress, clearStatus } from "./js/render.js";
import {
  addBatch,
  addFilesToActive,
  clearActiveBatch,
  clearAllBatches,
  getRunnableEntries,
  getSingleFileBatchLabels,
  moveItem,
  removeActiveBatch,
  removeItem,
  setActiveBatch,
  setBusy,
  state,
} from "./js/state.js";
import { downloadBlob, normalizeFileName } from "./js/utils.js";

const actions = {
  moveItem(fromIndex, toIndex) {
    moveItem(fromIndex, toIndex);
    renderApp();
  },
  removeItem(index) {
    removeItem(index);
    renderApp();
  },
  selectBatch(batchId) {
    if (state.isBusy) return;
    setActiveBatch(batchId);
    renderApp();
  },
};

function getNamingConfig() {
  return {
    mode: dom.namingMode.value,
    sequenceStart: dom.sequenceStart.value,
  };
}

function renderApp() {
  render(getNamingConfig(), actions);
}

function getReadyEntries() {
  const config = getNamingConfig();
  return getRunnableEntries().map(entry => ({
    ...entry,
    filename: getOutputNameForBatch(entry.batch, entry.index, config),
  }));
}

function addSelectedFiles(fileListLike) {
  if (state.isBusy) return;

  const result = addFilesToActive(fileListLike);
  renderApp();

  if (result.rejected.length > 0) {
    showStatus(`Ignored non-MP3 files:\n${result.rejected.join("\n")}`, false);
    return;
  }

  if (result.accepted.length > 0) {
    clearStatus();
  }
}

async function runReadyBatches() {
  if (state.isBusy) return;

  const singleFileBatches = getSingleFileBatchLabels();
  if (singleFileBatches.length > 0) {
    showStatus(`These batches need at least two MP3 files:\n${singleFileBatches.join("\n")}`, false);
    return;
  }

  const entries = getReadyEntries();
  if (entries.length === 0) return;

  const duplicateName = findDuplicateOutputName(entries);
  if (duplicateName) {
    showStatus(`Duplicate output filenames:\n${duplicateName}`, false);
    return;
  }

  const archiveName = normalizeFileName(dom.archiveNameInput.value, "mp3-batches.zip", ".zip");
  dom.archiveNameInput.value = archiveName;
  setBusy(true);
  renderApp();

  try {
    showStatus(`Uploading ${entries.length} ready batch${entries.length === 1 ? "" : "es"}...`, true);
    const zipBlob = await mergeBatches(entries, archiveName, percent => {
      updateProgress(percent, `Uploading ${entries.length} ready batch${entries.length === 1 ? "" : "es"}...`);
    });

    updateProgress(100, `Downloading ${archiveName}...`);
    downloadBlob(zipBlob, archiveName);
    showStatus(`Created ${archiveName} with ${entries.length} merged MP3 file${entries.length === 1 ? "" : "s"}.`, false);
  } catch (error) {
    showStatus(error.message || "The merge failed.", false);
  } finally {
    setBusy(false);
    renderApp();
  }
}

dom.dropZone.addEventListener("click", event => {
  if (state.isBusy || event.target.closest("button")) return;
  dom.fileInput.click();
});

dom.selectButton.addEventListener("click", () => {
  if (!state.isBusy) dom.fileInput.click();
});

dom.fileInput.addEventListener("change", event => {
  addSelectedFiles(event.target.files);
  dom.fileInput.value = "";
});

["dragenter", "dragover"].forEach(name => {
  dom.dropZone.addEventListener(name, event => {
    if (state.isBusy) return;
    event.preventDefault();
    dom.dropZone.classList.add("is-over");
  });
});

["dragleave", "drop"].forEach(name => {
  dom.dropZone.addEventListener(name, event => {
    event.preventDefault();
    dom.dropZone.classList.remove("is-over");
  });
});

dom.dropZone.addEventListener("drop", event => addSelectedFiles(event.dataTransfer.files));

dom.dropZone.addEventListener("keydown", event => {
  if (state.isBusy) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    dom.fileInput.click();
  }
});

dom.batchTabs.addEventListener("keydown", event => {
  if (state.isBusy || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();

  const currentIndex = state.batches.findIndex(batch => batch.id === state.activeBatchId);
  const offset = event.key === "ArrowRight" ? 1 : -1;
  const nextIndex = (currentIndex + offset + state.batches.length) % state.batches.length;
  setActiveBatch(state.batches[nextIndex].id);
  renderApp();
});

dom.addBatchButton.addEventListener("click", () => {
  if (state.isBusy) return;
  addBatch();
  clearStatus();
  renderApp();
});

dom.removeBatchButton.addEventListener("click", () => {
  if (state.isBusy) return;
  removeActiveBatch();
  clearStatus();
  renderApp();
});

dom.clearBatchButton.addEventListener("click", () => {
  if (state.isBusy) return;
  clearActiveBatch();
  clearStatus();
  renderApp();
});

dom.clearAllButton.addEventListener("click", () => {
  if (state.isBusy) return;
  clearAllBatches();
  clearStatus();
  renderApp();
});

dom.mergeButton.addEventListener("click", runReadyBatches);

dom.namingMode.addEventListener("change", () => {
  clearStatus();
  renderApp();
});

dom.sequenceStart.addEventListener("input", renderApp);

dom.archiveNameInput.addEventListener("blur", () => {
  dom.archiveNameInput.value = normalizeFileName(dom.archiveNameInput.value, "mp3-batches.zip", ".zip");
  renderApp();
});

dom.batchNameInput.addEventListener("input", event => {
  const activeBatch = state.batches.find(batch => batch.id === state.activeBatchId);
  if (activeBatch) {
    activeBatch.filename = event.target.value;
  }
  renderApp();
});

renderApp();
