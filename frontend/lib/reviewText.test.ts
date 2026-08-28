import { describe, expect, it } from "vitest";
import { normalizeReviewText } from "./reviewText";

describe("normalizeReviewText", () => {
  it("preserves real newlines and converts literal escaped newlines", () => {
    expect(normalizeReviewText("Dòng một\\nDòng hai\r\nDòng ba")).toBe("Dòng một\nDòng hai\nDòng ba");
  });

  it("does not translate or otherwise rewrite report content", () => {
    expect(normalizeReviewText("Xe giảm tốc đột ngột.")).toBe("Xe giảm tốc đột ngột.");
  });
});
