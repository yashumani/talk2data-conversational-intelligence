import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("static Pages entry", () => {
  it("declares a network-disabled CSP and no runtime endpoint API", () => {
    const html = readFileSync("pages/index.html", "utf8");
    expect(html).toContain("connect-src 'none'");
    expect(html).not.toMatch(/fetch\(|\/v1\/|api[_-]?key/i);
  });
});
