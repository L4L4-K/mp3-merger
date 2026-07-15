import { mergeBatch } from "./js/api.js";
import { dom } from "./js/dom.js";
import { buildMergeEntries } from "./js/jobs.js";
import { findDuplicateOutputName } from "./js/naming.js";
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
import { createZipArchive } from "./js/zip.js";

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

function defaultBatchFileName(batchIndex) {
  return `Batch${batchIndex + 1}.mp3`;
}

function applyDefaultNames() {
  dom.archiveNameInput.value = normalizeFileName(dom.archiveNameInput.value, "mp3-batches.zip", ".zip");

  if (!dom.sequenceStart.value.trim()) {
    dom.sequenceStart.value = "Section1";
  }

  state.batches.forEach((batch, index) => {
    if (!batch.filename.trim()) {
      batch.filename = defaultBatchFileName(index);
    }
  });

  const activeBatch = state.batches.find(batch => batch.id === state.activeBatchId);
  if (activeBatch && document.activeElement !== dom.batchNameInput) {
    dom.batchNameInput.value = activeBatch.filename;
  }
}

function getReadyEntries() {
  return buildMergeEntries(getRunnableEntries(), getNamingConfig());
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

  applyDefaultNames();
  renderApp();

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
    const mergedFiles = [];

    for (let index = 0; index < entries.length; index += 1) {
      const entry = entries[index];
      const current = index + 1;
      const total = entries.length;
      const basePercent = Math.round((index / total) * 90);

      showStatus(`Merging batch ${current} of ${total}: ${entry.filename} (completed ${index}/${total})`, true);
      updateProgress(basePercent, `Merging batch ${current} of ${total}: ${entry.filename} (completed ${index}/${total})`);

      const mp3Blob = await mergeBatch(entry, percent => {
        const uploadContribution = Math.round((percent / 100) * (70 / total));
        updateProgress(
          basePercent + uploadContribution,
          `Uploading batch ${current} of ${total}: ${entry.filename} (completed ${index}/${total})`,
        );
      });

      mergedFiles.push({ name: entry.filename, blob: mp3Blob });
      updateProgress(
        Math.round((current / total) * 90),
        `Finished batch ${current} of ${total}: ${entry.filename} (completed ${current}/${total})`,
      );
    }

    updateProgress(95, `Packaging ZIP archive: ${archiveName} (completed ${entries.length}/${entries.length})`);
    const zipBlob = await createZipArchive(mergedFiles);

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

dom.sequenceStart.addEventListener("blur", () => {
  if (!dom.sequenceStart.value.trim()) {
    dom.sequenceStart.value = "Section1";
  }
  renderApp();
});

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

dom.batchNameInput.addEventListener("blur", () => {
  const activeIndex = state.batches.findIndex(batch => batch.id === state.activeBatchId);
  const activeBatch = state.batches[activeIndex];
  if (!activeBatch) return;

  if (!activeBatch.filename.trim()) {
    activeBatch.filename = defaultBatchFileName(activeIndex);
  }
  dom.batchNameInput.value = activeBatch.filename;
  renderApp();
});

renderApp();
