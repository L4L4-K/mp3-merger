const crcTable = new Uint32Array(256);

for (let index = 0; index < crcTable.length; index += 1) {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  crcTable[index] = value >>> 0;
}

function updateCrc32(crc, bytes) {
  for (const byte of bytes) {
    crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return crc;
}

async function crc32(blob) {
  let crc = 0xffffffff;
  if (typeof blob.stream !== "function") {
    return (updateCrc32(crc, new Uint8Array(await blob.arrayBuffer())) ^ 0xffffffff) >>> 0;
  }

  const reader = blob.stream().getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      crc = updateCrc32(crc, value);
    }
  } finally {
    reader.releaseLock();
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date = new Date()) {
  const year = Math.max(date.getFullYear(), 1980);
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const dosDate = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { dosDate, dosTime };
}

function writeUint16(view, offset, value) {
  view.setUint16(offset, value, true);
}

function writeUint32(view, offset, value) {
  view.setUint32(offset, value, true);
}

function localFileHeader(nameBytes, entry) {
  const header = new Uint8Array(30 + nameBytes.length);
  const view = new DataView(header.buffer);
  writeUint32(view, 0, 0x04034b50);
  writeUint16(view, 4, 20);
  writeUint16(view, 6, 0x0800);
  writeUint16(view, 8, 0);
  writeUint16(view, 10, entry.dosTime);
  writeUint16(view, 12, entry.dosDate);
  writeUint32(view, 14, entry.crc);
  writeUint32(view, 18, entry.size);
  writeUint32(view, 22, entry.size);
  writeUint16(view, 26, nameBytes.length);
  writeUint16(view, 28, 0);
  header.set(nameBytes, 30);
  return header;
}

function centralDirectoryHeader(nameBytes, entry, localHeaderOffset) {
  const header = new Uint8Array(46 + nameBytes.length);
  const view = new DataView(header.buffer);
  writeUint32(view, 0, 0x02014b50);
  writeUint16(view, 4, 20);
  writeUint16(view, 6, 20);
  writeUint16(view, 8, 0x0800);
  writeUint16(view, 10, 0);
  writeUint16(view, 12, entry.dosTime);
  writeUint16(view, 14, entry.dosDate);
  writeUint32(view, 16, entry.crc);
  writeUint32(view, 20, entry.size);
  writeUint32(view, 24, entry.size);
  writeUint16(view, 28, nameBytes.length);
  writeUint16(view, 30, 0);
  writeUint16(view, 32, 0);
  writeUint16(view, 34, 0);
  writeUint16(view, 36, 0);
  writeUint32(view, 38, 0);
  writeUint32(view, 42, localHeaderOffset);
  header.set(nameBytes, 46);
  return header;
}

function endOfCentralDirectory(entryCount, centralDirectorySize, centralDirectoryOffset) {
  const header = new Uint8Array(22);
  const view = new DataView(header.buffer);
  writeUint32(view, 0, 0x06054b50);
  writeUint16(view, 4, 0);
  writeUint16(view, 6, 0);
  writeUint16(view, 8, entryCount);
  writeUint16(view, 10, entryCount);
  writeUint32(view, 12, centralDirectorySize);
  writeUint32(view, 16, centralDirectoryOffset);
  writeUint16(view, 20, 0);
  return header;
}

export async function createZipArchive(files) {
  const encoder = new TextEncoder();
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const file of files) {
    const nameBytes = encoder.encode(file.name);
    const entry = {
      ...dosDateTime(),
      crc: await crc32(file.blob),
      size: file.blob.size,
    };

    const localHeader = localFileHeader(nameBytes, entry);
    const centralHeader = centralDirectoryHeader(nameBytes, entry, offset);
    localParts.push(localHeader, file.blob);
    centralParts.push(centralHeader);
    offset += localHeader.byteLength + file.blob.size;
  }

  const centralDirectoryOffset = offset;
  const centralDirectorySize = centralParts.reduce((sum, part) => sum + part.byteLength, 0);
  const endRecord = endOfCentralDirectory(files.length, centralDirectorySize, centralDirectoryOffset);

  return new Blob([...localParts, ...centralParts, endRecord], { type: "application/zip" });
}
