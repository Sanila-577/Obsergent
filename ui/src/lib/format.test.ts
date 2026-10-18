import { formatCount, formatMs, formatPercent, prettyJson, shortId, splitList, timeAgo } from "./format";

describe("formatMs", () => {
  it.each([[0.4, "0.40 ms"], [12.34, "12.3 ms"], [340, "340 ms"], [1520, "1.52 s"], [125_000, "2 m 5 s"]])("%s -> %s", (input, expected) => {
    expect(formatMs(input)).toBe(expected);
  });
  it("shows a dash for missing values", () => {
    expect(formatMs(null)).toBe("-");
    expect(formatMs(undefined)).toBe("-");
    expect(formatMs(NaN)).toBe("-");
  });
});

describe("other formatters", () => {
  it("shortens big counts", () => {
    expect(formatCount(950)).toBe("950");
    expect(formatCount(12_500)).toBe("12.5k");
    expect(formatCount(null)).toBe("-");
  });
  it("formats percentages", () => {
    expect(formatPercent(0.014)).toBe("1.4%");
    expect(formatPercent(0)).toBe("0.0%");
    expect(formatPercent(0.0004)).toBe("0.04%");
  });
  it("says how long ago something happened", () => {
    const now = Date.UTC(2026, 9, 17, 12, 0, 0);
    const ago = (seconds: number) => timeAgo((now - seconds * 1000) * 1_000_000, now);
    expect(ago(12)).toBe("12 s ago");
    expect(ago(180)).toBe("3 min ago");
    expect(ago(7200)).toBe("2 h ago");
    expect(ago(3 * 86_400)).toBe("3 d ago");
  });
  it("splits the comma lists the API returns", () => {
    expect(splitList("a,b,,c")).toEqual(["a", "b", "c"]);
    expect(splitList(null)).toEqual([]);
    expect(shortId("abcdef0123456789")).toBe("abcdef01");
  });
  it("pretty-prints JSON objects but leaves other text alone", () => {
    expect(prettyJson('{"a":1}')).toEqual({ pretty: '{\n  "a": 1\n}', isJson: true });
    expect(prettyJson("just text")).toEqual({ pretty: "just text", isJson: false });
    expect(prettyJson("42").isJson).toBe(false); // a bare number is not worth pretty-printing
  });
});
