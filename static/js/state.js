import { compareFilesAscending, createId, isMp3 } from "./utils.js";

/**
 * @typedef {File} AudioFile
 * @typedef {{id: string, file: AudioFile}} BatchItem
 * @typedef {{id: string, filename: string, items: BatchItem[]}} Batch
 * @typedef {{
 *   activeBatchId: string,
 *   batches: Batch[],
 *   dragSourceId: string | null,
 *   isBusy: boolean,
 * }} AppState
 */

/** @type {AppState} */
export const state = {
  activeBatchId: "",
  batches: [createBatch(1)],
  dragSourceId: null,
  isBusy: false,
};

state.activeBatchId = state.batches[0].id;

export function createBatch(number) {
  return {
    id: createId(),
    filename: `Batch${number}.mp3`,
    items: [],
  };
}

export function getActiveBatch() {
  const active = state.batches.find(batch => batch.id === state.activeBatchId);
  if (active) return active;
  state.activeBatchId = state.batches[0].id;
  return state.batches[0];
}

export function getBatchIndex(batchId) {
  return Math.max(0, state.batches.findIndex(batch => batch.id === batchId));
}

export function setActiveBatch(batchId) {
  if (state.batches.some(batch => batch.id === batchId)) {
    state.activeBatchId = batchId;
  }
}

export function getTotalFiles() {
  return state.batches.reduce((sum, batch) => sum + batch.items.length, 0);
}

export function getTotalBytes() {
  return state.batches.reduce(
    (sum, batch) => sum + batch.items.reduce((batchSum, item) => batchSum + item.file.size, 0),
    0,
  );
}

export function getRunnableEntries() {
  return state.batches
    .map((batch, index) => ({ batch, index }))
    .filter(entry => entry.batch.items.length >= 2);
}

export function getSingleFileBatchLabels() {
  return state.batches
    .map((batch, index) => ({ batch, label: `Batch ${index + 1}` }))
    .filter(entry => entry.batch.items.length === 1)
    .map(entry => entry.label);
}

export function addFilesToActive(fileListLike) {
  const batch = getActiveBatch();
  const files = Array.from(fileListLike || []);
  const accepted = [];
  const rejected = [];

  for (const file of files) {
    if (!isMp3(file)) {
      rejected.push(file.name);
      continue;
    }
    accepted.push(file);
  }

  accepted.sort(compareFilesAscending);
  batch.items.push(...accepted.map(file => ({ id: createId(), file })));

  return { accepted, rejected };
}

export function moveItem(fromIndex, toIndex) {
  const batch = getActiveBatch();
  if (
    !Number.isInteger(fromIndex) ||
    !Number.isInteger(toIndex) ||
    fromIndex < 0 ||
    fromIndex >= batch.items.length ||
    toIndex < 0 ||
    toIndex >= batch.items.length ||
    fromIndex === toIndex
  ) return;
  const [item] = batch.items.splice(fromIndex, 1);
  batch.items.splice(toIndex, 0, item);
}

export function removeItem(index) {
  const batch = getActiveBatch();
  if (!Number.isInteger(index) || index < 0 || index >= batch.items.length) return;
  batch.items.splice(index, 1);
}

export function addBatch() {
  const batch = createBatch(state.batches.length + 1);
  state.batches.push(batch);
  state.activeBatchId = batch.id;
}

export function removeActiveBatch() {
  if (state.batches.length <= 1) return;
  const activeIndex = getBatchIndex(state.activeBatchId);
  state.batches.splice(activeIndex, 1);
  state.activeBatchId = state.batches[Math.max(0, activeIndex - 1)].id;
}

export function clearActiveBatch() {
  getActiveBatch().items = [];
}

export function clearAllBatches() {
  state.batches = [createBatch(1)];
  state.activeBatchId = state.batches[0].id;
}

export function setBusy(value) {
  state.isBusy = Boolean(value);
}
