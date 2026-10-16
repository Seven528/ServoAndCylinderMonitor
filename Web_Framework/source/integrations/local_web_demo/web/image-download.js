import { api, artifactBlob, saveDownload } from "./transport.js";

export async function imageDownload(artifact, format) {
  if (format === "svg") {
    if (!artifact.presentation_id)
      throw new Error("此图片没有可追溯的场景身份，无法导出矢量图。");
    const result = await api(
      "export-image",
      {
        presentation_id: artifact.presentation_id,
        format: "svg",
      },
      { timeout: 120000 },
    );
    return {
      blob: await artifactBlob({
        ...result.artifact,
        server_id: artifact.server_id,
      }),
      name: result.artifact.name,
    };
  }
  const source = await artifactBlob(artifact);
  if (format === "png") return { blob: source, name: artifact.name };
  if (format !== "jpg") throw new Error("不支持的下载格式。");
  const bitmap = await createImageBitmap(source);
  const canvas = document.createElement("canvas");
  try {
    if (
      bitmap.width < 1 ||
      bitmap.height < 1 ||
      Math.max(bitmap.width, bitmap.height) > 2400
    )
      throw new Error("图片尺寸超出导出范围。");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const painter = canvas.getContext("2d");
    painter.fillStyle = "#F6F8F8";
    painter.fillRect(0, 0, canvas.width, canvas.height);
    painter.drawImage(bitmap, 0, 0);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.95),
    );
    if (!blob || blob.size > 16 * 1024 * 1024)
      throw new Error("JPG 编码失败或超过大小限制。");
    return {
      blob,
      name: (artifact.name || "pcb-image").replace(/\.[^.]+$/, "") + ".jpg",
    };
  } finally {
    bitmap.close();
    canvas.width = canvas.height = 1;
  }
}
export function bindImageDownload(button, artifact, onError, onStart, onDone) {
  button.hidden = !artifact;
  button.onclick = async (event) => {
    event.preventDefault();
    if (!artifact || button.dataset.downloading) return;
    button.dataset.downloading = "true";
    button.disabled = true;
    const format = document.getElementById("download-format").value;
    try {
      onStart?.(format);
      const value = await imageDownload(artifact, format);
      saveDownload(value.blob, value.name);
      onDone?.();
    } catch (error) {
      onError(error);
    } finally {
      delete button.dataset.downloading;
      button.disabled = false;
    }
  };
}
