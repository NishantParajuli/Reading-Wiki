import React from "react";
import { Illustration } from "../codex/index.js";
import { paragraphIllustrations } from "./illustrationPlacement.js";

export function NarratedProse({ prepared, justify, indent, illustrations = [] }) {
  const className = "reader-text" + (justify ? " justify" : "") + (indent ? " indent" : "");
  const slots = paragraphIllustrations(prepared.paragraphs, illustrations);
  const renderSlot = index => (slots.get(index) || []).map(item => <Illustration key={item.id} item={item} inline />);
  return (
    <div className={className}>
      {renderSlot(0)}
      {prepared.paragraphs.map((paragraph, index) => (
        <React.Fragment key={index}><p>
          {paragraph.chunks.map(chunk => (
            <span key={chunk.index} data-narration-chunk={chunk.index}>{chunk.text}</span>
          ))}
        </p>{renderSlot(index + 1)}</React.Fragment>
      ))}
    </div>
  );
}
