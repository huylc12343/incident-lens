export function normalizeReviewText(value?: string | null) {
  if (!value) return "";
  return value
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\n")
    .replace(/\r\n?/g, "\n");
}
