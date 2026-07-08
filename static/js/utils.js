const fileNameLocales = ["en", "ja"];
const fileNameCollator = new Intl.Collator(fileNameLocales, {
  numeric: true,
  sensitivity: "base",
});
const fileNameTieBreaker = new Intl.Collator(fileNameLocales, {
  numeric: false,
  sensitivity: "variant",
});

export function createId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function isMp3(file) {
  const type = (file.type || "").toLowerCase();
  return file.name.toLowerCase().endsWith(".mp3") || type === "audio/mpeg" || type === "audio/mp3";
}

export function getFileNameSortKey(name) {
  return String(name || "")
    .normalize("NFKC")
    .trim();
}

export function compareFilesAscending(a, b) {
  const leftKey = getFileNameSortKey(a.name);
  const rightKey = getFileNameSortKey(b.name);
  const primary = fileNameCollator.compare(leftKey, rightKey);
  if (primary !== 0) return primary;

  const secondary = fileNameTieBreaker.compare(leftKey, rightKey);
  if (secondary !== 0) return secondary;

  return String(a.name || "").localeCompare(String(b.name || ""), fileNameLocales);
}

export function normalizeFileName(name, fallback, extension) {
  const sanitized = String(name || "")
    .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, "_")
    .trim()
    .replace(/^\.+|\.+$/g, "");
  const value = sanitized || fallback;
  return value.toLowerCase().endsWith(extension.toLowerCase()) ? value : `${value}${extension}`;
}

export function titleFromFileName(fileName) {
  return String(fileName || "")
    .replace(/\.mp3$/i, "")
    .trim() || "Merged MP3";
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
