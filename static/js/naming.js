import { normalizeFileName } from "./utils.js";

export function getSequentialName(batchIndex, sequenceStart) {
  const startName = normalizeFileName(sequenceStart, "Section1.mp3", ".mp3");
  const match = startName.match(/^(.*?)(\d+)(\.mp3)$/i);

  if (!match) {
    return startName.replace(/\.mp3$/i, `${batchIndex + 1}.mp3`);
  }

  const prefix = match[1];
  const startNumber = Number(match[2]);
  const width = match[2].length;
  const extension = match[3];
  const nextNumber = String(startNumber + batchIndex).padStart(width, "0");
  return `${prefix}${nextNumber}${extension}`;
}

export function getOutputNameForBatch(batch, batchIndex, config) {
  if (config.mode === "sequence") {
    return getSequentialName(batchIndex, config.sequenceStart);
  }
  return normalizeFileName(batch.filename, `Batch${batchIndex + 1}.mp3`, ".mp3");
}

export function findDuplicateOutputName(entries) {
  const seen = new Map();
  for (const entry of entries) {
    const key = entry.filename.toLocaleLowerCase();
    if (seen.has(key)) {
      return `${seen.get(key)} / Batch ${entry.index + 1}: ${entry.filename}`;
    }
    seen.set(key, `Batch ${entry.index + 1}`);
  }
  return "";
}
