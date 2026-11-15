export const ACCEPT = [".pdf", ".md", ".markdown", ".html", ".htm", ".txt"];
export const MAX_BYTES = 25 * 1024 * 1024;

const BY_EXT: Record<string, string> = {
  md: "text/markdown", markdown: "text/markdown", html: "text/html", htm: "text/html", txt: "text/plain", pdf: "application/pdf",
};

export function mimeOf(file: File): string {
  if (file.type) return file.type;
  return BY_EXT[file.name.toLowerCase().split(".").pop() ?? ""] ?? "application/octet-stream";
}

/** Client-side checks before upload; the API enforces the same rules. */
export function validateFile(file: File): string | null {
  if (!ACCEPT.some((ext) => file.name.toLowerCase().endsWith(ext))) return "Unsupported type (PDF, Markdown, HTML or text).";
  if (file.size > MAX_BYTES) return "Larger than 25 MB.";
  if (file.size === 0) return "The file is empty.";
  return null;
}
