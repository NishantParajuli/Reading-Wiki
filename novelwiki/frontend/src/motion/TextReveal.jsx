/* Word-by-word "rising tide" reveal for display type.
   The text stays a single accessible string (spaces are real text nodes);
   each word rises out of a clipped line box. CSS-only, so it costs nothing
   after the first frame and collapses under reduced motion. */
import React from "react";

export function TextReveal({ as: Tag = "span", text, children, className = "", delay = 0, step = 70, ...rest }) {
  const source = text ?? (typeof children === "string" || typeof children === "number" ? String(children) : null);
  if (source == null) return <Tag className={className} {...rest}>{children}</Tag>;
  const parts = source.split(/(\s+)/);
  let index = 0;
  return (
    <Tag className={["text-reveal", className].filter(Boolean).join(" ")} {...rest}>
      {parts.map((part, key) => (/^\s+$/.test(part) || part === ""
        ? part
        : (
          <span className="tr-word" key={key}>
            <span className="tr-inner" style={{ "--i": index++, "--tr-delay": `${delay}ms`, "--tr-step": `${step}ms` }}>{part}</span>
          </span>
        )))}
    </Tag>
  );
}
