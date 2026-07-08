async function extractErrorMessage(xhr) {
  const fallback = xhr.statusText || "The merge failed.";
  const response = xhr.response;

  if (response instanceof Blob) {
    const text = await response.text();
    if (!text) return fallback;
    try {
      const body = JSON.parse(text);
      return body.detail || fallback;
    } catch {
      return text || fallback;
    }
  }

  return fallback;
}

export function mergeBatch(entry, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    entry.batch.items.forEach(item => formData.append("files", item.file, item.file.name));
    formData.append("title", entry.title || entry.filename.replace(/\.mp3$/i, ""));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/merge");
    xhr.responseType = "blob";

    xhr.upload.addEventListener("progress", event => {
      if (!event.lengthComputable) return;
      onProgress(Math.round((event.loaded / event.total) * 85));
    });

    xhr.addEventListener("load", async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response);
        return;
      }
      reject(new Error(await extractErrorMessage(xhr)));
    });

    xhr.addEventListener("error", () => {
      reject(new Error("Network error. Check that the server is running."));
    });

    xhr.send(formData);
  });
}
