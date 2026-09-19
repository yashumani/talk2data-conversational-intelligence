const canned = Object.freeze([
  "The preview separates language interpretation from deterministic data execution.",
  "A production Talk2Data answer must be authorized, source-backed, validated, and receipt-bound.",
  "This local preview does not connect to data, execute SQL, or release numerical claims.",
]);

export async function runPreviewModel(prompt, { signal } = {}) {
  if (signal?.aborted) throw signal.reason;
  const normalized = prompt.trim().replace(/\s+/g, " ");
  if (!normalized) throw new TypeError("prompt is required");
  const index = [...normalized].reduce((sum, character) => sum + character.codePointAt(0), 0) % canned.length;
  await Promise.resolve();
  if (signal?.aborted) throw signal.reason;
  return `${canned[index]} Preview input: “${normalized.slice(0, 180)}${normalized.length > 180 ? "…" : ""}”`;
}
