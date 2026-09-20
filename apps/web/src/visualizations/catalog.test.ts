import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { acceptedVisualizations, queuedVisualizations, VISUALIZATION_REGISTRY } from "./catalog";

describe("visualization registry", () => {
  it("has a finite eight-batch release contract", () => {
    expect(VISUALIZATION_REGISTRY).toHaveLength(76);
    expect(acceptedVisualizations).toHaveLength(25);
    expect(queuedVisualizations).toHaveLength(51);
    expect([...new Set(VISUALIZATION_REGISTRY.map((entry) => entry.batch))]).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("keeps identifiers unique and accepts only completed batches", () => {
    const ids = VISUALIZATION_REGISTRY.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(acceptedVisualizations.every((entry) => entry.batch <= 2)).toBe(true);
    expect(queuedVisualizations.every((entry) => entry.batch > 2)).toBe(true);
  });

  it("matches the durable JSON registry and normalized taxonomy", () => {
    const registry = JSON.parse(readFileSync("../../contracts/visualization_registry.v1.json", "utf8"));
    const taxonomy = JSON.parse(readFileSync("../../contracts/visualization_source_taxonomy.v1.json", "utf8"));
    expect(registry.entries.map((entry: { id: string }) => entry.id)).toEqual(VISUALIZATION_REGISTRY.map((entry) => entry.id));
    expect(taxonomy.targets).toHaveLength(44);
    expect(new Set(taxonomy.targets).size).toBe(44);
    expect(VISUALIZATION_REGISTRY.every((entry) => taxonomy.targets.includes(entry.target))).toBe(true);
  });

  it("exports immutable entries", () => {
    expect(Object.isFrozen(VISUALIZATION_REGISTRY)).toBe(true);
    expect(VISUALIZATION_REGISTRY.every(Object.isFrozen)).toBe(true);
  });
});
