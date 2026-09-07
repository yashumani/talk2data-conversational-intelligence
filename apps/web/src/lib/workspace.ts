import type { ChatResult, Source } from "./contracts.ts";

export function suggestedAnchor(source: Source): string {
  const day = new Date(source.coverage_end + "T12:00:00Z");
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

export function matchesSource(result: ChatResult | null, source: Source | null): boolean {
  return Boolean(result?.receipt && source
    && result.receipt.source_fingerprint === source.source_fingerprint);
}

export function checkFile(file: Pick<File, "size" | "name">, maximumBytes: number): string | null {
  if (!file.name.toLowerCase().endsWith(".csv")) return "Choose a .csv file using the supplied template.";
  if (file.size === 0 || file.size > maximumBytes) return "The file is empty or exceeds the upload limit.";
  return null;
}
