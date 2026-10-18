// Word-level text diff as the API returns it: inserted words green, removed words red.
import type { DiffSegment } from "../api/types";

export function DiffText({ segments }: { segments: DiffSegment[] }) {
  return (
    <p className="diff" style={{ margin: 0, lineHeight: 1.7 }}>
      {segments.map((segment, index) =>
        segment.op === "insert" ? <ins key={index}>{segment.text} </ins>
        : segment.op === "delete" ? <del key={index}>{segment.text} </del>
        : <span key={index}>{segment.text} </span>)}
    </p>
  );
}
