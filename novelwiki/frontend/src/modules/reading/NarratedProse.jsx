import React from "react";

export function NarratedProse({ prepared, justify, indent }) {
  const className = "reader-text" + (justify ? " justify" : "") + (indent ? " indent" : "");
  return (
    <div className={className}>
      {prepared.paragraphs.map((paragraph, index) => (
        <p key={index}>
          {paragraph.chunks.map(chunk => (
            <span key={chunk.index} data-narration-chunk={chunk.index}>{chunk.text}</span>
          ))}
        </p>
      ))}
    </div>
  );
}
