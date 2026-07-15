import { getOutputNameForBatch } from "./naming.js";
import { titleFromFileName } from "./utils.js";

/**
 * @typedef {{filename: string, items: Array<unknown>}} MergeBatch
 * @typedef {{batch: MergeBatch, index: number}} RunnableEntry
 * @typedef {RunnableEntry & {filename: string, title: string}} MergeEntry
 *
 * @param {RunnableEntry[]} runnableEntries
 * @param {{mode: "custom" | "sequence", sequenceStart: string}} namingConfig
 * @returns {MergeEntry[]}
 */
export function buildMergeEntries(runnableEntries, namingConfig) {
  return runnableEntries.map(entry => {
    const filename = getOutputNameForBatch(entry.batch, entry.index, namingConfig);
    return {
      ...entry,
      filename,
      title: titleFromFileName(filename),
    };
  });
}
