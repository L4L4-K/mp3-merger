import assert from "node:assert/strict";
import test from "node:test";

import { buildMergeEntries } from "../../static/js/jobs.js";
import {
  findDuplicateOutputName,
  getOutputNameForBatch,
  getSequentialName,
} from "../../static/js/naming.js";
import {
  addBatch,
  addFilesToActive,
  clearAllBatches,
  getRunnableEntries,
  getSingleFileBatchLabels,
  getTotalBytes,
  getTotalFiles,
  moveItem,
  removeActiveBatch,
  removeItem,
  setActiveBatch,
  setBusy,
  state,
} from "../../static/js/state.js";
import {
  compareFilesAscending,
  isMp3,
  normalizeFileName,
  titleFromFileName,
} from "../../static/js/utils.js";
import { createZipArchive } from "../../static/js/zip.js";

function audioFile(name, size = 1, type = "audio/mpeg") {
  return { name, size, type };
}

test("MP3 detection preserves the existing extension-or-MIME contract", () => {
  assert.equal(isMp3(audioFile("track.mp3", 1, "text/plain")), true);
  assert.equal(isMp3(audioFile("track.wav", 1, "audio/mpeg")), true);
  assert.equal(isMp3(audioFile("track.wav", 1, "audio/wav")), false);
});

test("filename comparison is numeric and deterministic", () => {
  const files = [
    audioFile("Track10.mp3"),
    audioFile("track2.mp3"),
    audioFile("Track1.mp3"),
  ];

  files.sort(compareFilesAscending);

  assert.deepEqual(
    files.map(file => file.name),
    ["Track1.mp3", "track2.mp3", "Track10.mp3"],
  );
});

test("filename and title normalization preserve current edge cases", () => {
  assert.equal(
    normalizeFileName('  ../bad:name?.MP3  ', "fallback.mp3", ".mp3"),
    "_bad_name_.MP3",
  );
  assert.equal(normalizeFileName("...", "fallback", ".zip"), "fallback.zip");
  assert.equal(titleFromFileName("Chapter.MP3"), "Chapter");
  assert.equal(titleFromFileName("  Chapter.MP3  "), "Chapter.MP3");
  assert.equal(titleFromFileName(".mp3"), "Merged MP3");
});

test("sequential and custom naming contracts remain stable", () => {
  assert.equal(getSequentialName(1, "Section1"), "Section2.mp3");
  assert.equal(getSequentialName(1, "Part009"), "Part010.mp3");
  assert.equal(getSequentialName(1, "Part"), "Part2.mp3");
  assert.equal(
    getOutputNameForBatch(
      { filename: "Custom", items: [] },
      4,
      { mode: "custom", sequenceStart: "Ignored1" },
    ),
    "Custom.mp3",
  );
});

test("duplicate output names remain case-insensitive", () => {
  assert.equal(
    findDuplicateOutputName([
      { index: 0, filename: "One.mp3" },
      { index: 2, filename: "one.MP3" },
    ]),
    "Batch 1 / Batch 3: one.MP3",
  );
});

test("merge-entry construction preserves original batch indexes and title derivation", () => {
  const batch = { id: "batch", filename: "Chapter.MP3", items: [] };

  const entries = buildMergeEntries(
    [{ batch, index: 4 }],
    { mode: "custom", sequenceStart: "Ignored1" },
  );

  assert.deepEqual(entries, [
    {
      batch,
      index: 4,
      filename: "Chapter.MP3",
      title: "Chapter",
    },
  ]);

  assert.deepEqual(
    buildMergeEntries([{ batch, index: 4 }], { mode: "sequence", sequenceStart: "Section1" }),
    [{ batch, index: 4, filename: "Section5.mp3", title: "Section5" }],
  );
});

test("new selections are sorted before append without re-sorting existing items", () => {
  clearAllBatches();

  const first = addFilesToActive([
    audioFile("Track10.mp3", 10),
    audioFile("Track2.mp3", 2),
    audioFile("notes.txt", 3, "text/plain"),
  ]);
  const second = addFilesToActive([audioFile("Track1.mp3", 1)]);

  assert.deepEqual(first.rejected, ["notes.txt"]);
  assert.equal(second.rejected.length, 0);
  assert.deepEqual(
    state.batches[0].items.map(item => item.file.name),
    ["Track2.mp3", "Track10.mp3", "Track1.mp3"],
  );
  assert.equal(getTotalFiles(), 3);
  assert.equal(getTotalBytes(), 13);
});

test("valid state transitions retain ordering, selection, and busy semantics", () => {
  clearAllBatches();
  addFilesToActive([audioFile("One.mp3"), audioFile("Two.mp3")]);

  moveItem(0, 1);
  assert.deepEqual(
    state.batches[0].items.map(item => item.file.name),
    ["Two.mp3", "One.mp3"],
  );
  removeItem(0);
  assert.deepEqual(state.batches[0].items.map(item => item.file.name), ["One.mp3"]);
  assert.deepEqual(getSingleFileBatchLabels(), ["Batch 1"]);

  addBatch();
  const secondBatchId = state.activeBatchId;
  addFilesToActive([audioFile("Three.mp3"), audioFile("Four.mp3")]);
  assert.deepEqual(
    getRunnableEntries().map(entry => entry.index),
    [1],
  );

  setActiveBatch(state.batches[0].id);
  assert.equal(state.activeBatchId, state.batches[0].id);
  setActiveBatch(secondBatchId);
  removeActiveBatch();
  assert.equal(state.batches.length, 1);

  setBusy(1);
  assert.equal(state.isBusy, true);
  setBusy(0);
  assert.equal(state.isBusy, false);
});

test("invalid item indexes cannot mutate the active batch", () => {
  clearAllBatches();
  addFilesToActive([audioFile("One.mp3"), audioFile("Two.mp3")]);
  const originalItems = [...state.batches[0].items];

  moveItem(-1, 0);
  moveItem(0, state.batches[0].items.length);
  removeItem(-1);
  removeItem(state.batches[0].items.length);

  assert.deepEqual(state.batches[0].items, originalItems);
});

test("ZIP generation preserves STORE entries, UTF-8 names, CRC, and order", async () => {
  const streamedBlob = new Blob([new TextEncoder().encode("abc")]);
  const originalStream = streamedBlob.stream.bind(streamedBlob);
  streamedBlob.arrayBuffer = async () => {
    throw new Error("ZIP input must not be copied through arrayBuffer()");
  };
  streamedBlob.stream = () => {
    const reader = originalStream().getReader();
    return new ReadableStream({
      async pull(controller) {
        const { done, value } = await reader.read();
        if (done) {
          controller.close();
          return;
        }
        for (const byte of value) {
          controller.enqueue(Uint8Array.of(byte));
        }
      },
    });
  };

  const archive = await createZipArchive([
    { name: "one.txt", blob: streamedBlob },
    { name: "二.txt", blob: new Blob([new TextEncoder().encode("xyz")]) },
  ]);
  const bytes = new Uint8Array(await archive.arrayBuffer());
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const decoder = new TextDecoder();
  const expectedEntries = [
    { name: "one.txt", content: "abc", crc: 0x352441c2 },
    { name: "二.txt", content: "xyz", crc: 0xeb8eba67 },
  ];
  const localOffsets = [];
  let offset = 0;

  assert.equal(archive.type, "application/zip");
  for (const expected of expectedEntries) {
    localOffsets.push(offset);
    assert.equal(view.getUint32(offset, true), 0x04034b50);
    assert.equal(view.getUint16(offset + 6, true), 0x0800);
    assert.equal(view.getUint16(offset + 8, true), 0);
    const crc = view.getUint32(offset + 14, true);
    const size = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const nameStart = offset + 30;
    const contentStart = nameStart + nameLength;

    assert.equal(decoder.decode(bytes.slice(nameStart, contentStart)), expected.name);
    assert.equal(decoder.decode(bytes.slice(contentStart, contentStart + size)), expected.content);
    assert.equal(crc, expected.crc);
    offset = contentStart + size;
  }

  assert.equal(view.getUint32(offset, true), 0x02014b50);
  const endOffset = bytes.byteLength - 22;
  assert.equal(view.getUint32(endOffset, true), 0x06054b50);
  assert.equal(view.getUint16(endOffset + 8, true), 2);
  assert.equal(view.getUint16(endOffset + 10, true), 2);
  assert.equal(view.getUint32(endOffset + 16, true), offset);
  assert.equal(view.getUint32(endOffset + 12, true), endOffset - offset);

  let centralOffset = offset;
  for (const [index, expected] of expectedEntries.entries()) {
    assert.equal(view.getUint32(centralOffset, true), 0x02014b50);
    assert.equal(view.getUint16(centralOffset + 8, true), 0x0800);
    assert.equal(view.getUint16(centralOffset + 10, true), 0);
    assert.equal(view.getUint32(centralOffset + 16, true), expected.crc);
    const nameLength = view.getUint16(centralOffset + 28, true);
    const extraLength = view.getUint16(centralOffset + 30, true);
    const commentLength = view.getUint16(centralOffset + 32, true);
    const nameStart = centralOffset + 46;
    assert.equal(decoder.decode(bytes.slice(nameStart, nameStart + nameLength)), expected.name);
    assert.equal(view.getUint32(centralOffset + 42, true), localOffsets[index]);
    centralOffset = nameStart + nameLength + extraLength + commentLength;
  }
  assert.equal(centralOffset, endOffset);
});

test("empty ZIP remains a valid empty central directory", async () => {
  const archive = await createZipArchive([]);
  const bytes = new Uint8Array(await archive.arrayBuffer());
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  assert.equal(bytes.byteLength, 22);
  assert.equal(view.getUint32(0, true), 0x06054b50);
  assert.equal(view.getUint16(8, true), 0);
  assert.equal(view.getUint16(10, true), 0);
});
