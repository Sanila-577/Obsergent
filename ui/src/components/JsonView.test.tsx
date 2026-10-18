import { render, screen } from "@testing-library/react";
import { DiffText } from "./DiffText";
import { JsonView } from "./JsonView";

describe("JsonView", () => {
  it("pretty-prints JSON text", () => {
    const { container } = render(<JsonView value='{"query":"python"}' />);
    expect(container.textContent).toContain('"query": "python"');
  });

  it("highlights what AgentTrace hid and explains it", () => {
    render(<JsonView value='{"api_key": "***", "note": "key ***"}' />);
    const hidden = screen.getAllByTitle(/hidden by agenttrace/i);
    expect(hidden).toHaveLength(2); // the whole value, and the part inside a longer string
    expect(hidden[0]).toHaveTextContent("***");
    expect(hidden[0]).toHaveClass("redacted");
  });

  it("shows plain text unchanged and a message for nothing", () => {
    const { container, rerender } = render(<JsonView value="just text" />);
    expect(container.textContent).toBe("just text");
    rerender(<JsonView value="" empty="nothing here" />);
    expect(screen.getByText("nothing here")).toBeInTheDocument();
  });
});

describe("DiffText", () => {
  it("marks inserted and removed words", () => {
    const { container } = render(<DiffText segments={[{ op: "equal", text: "Search" }, { op: "delete", text: "books" }, { op: "insert", text: "books. Also send" }]} />);
    expect(container.querySelector("del")).toHaveTextContent("books");
    expect(container.querySelector("ins")).toHaveTextContent("books. Also send");
  });
});
