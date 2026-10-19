import { describe, expect, it } from "vitest";
import vectors from "../../../tests/fixtures/model_names.json";
import { displayModel, perMillion } from "./models";

describe("displayModel", () => {
  it("gives every shared example the same name the Python code gives it", () => {
    for (const example of vectors) expect(displayModel(example.name)).toBe(example.display);
  });

  it("shows the dated and the undated name as one model", () => {
    expect(displayModel("gpt-4o-mini-2024-07-18")).toBe(displayModel("gpt-4o-mini"));
    expect(displayModel(null)).toBe("unknown model");
  });
});

describe("perMillion", () => {
  it("is always dollars", () => {
    expect(perMillion(0.15)).toBe("$0.15");
    expect(perMillion(0.075)).toBe("$0.075");
    expect(perMillion(3)).toBe("$3.00");
    expect(perMillion(null)).toBe("-");
  });
});
