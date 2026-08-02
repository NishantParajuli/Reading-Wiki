const RICH_NARRATION_BLOCKS = "p, li, blockquote, h2, h3, h4, figcaption, .caption";
const MAX_SENTENCES_PER_CHUNK = 2;
const SHORT_CHUNK_CHARS = 140;

let sentenceSegmenter;

function sentenceSegments(text) {
  if (!text) return [];
  if (typeof Intl !== "undefined" && typeof Intl.Segmenter === "function") {
    sentenceSegmenter ||= new Intl.Segmenter(undefined, { granularity: "sentence" });
    return Array.from(sentenceSegmenter.segment(text), ({ segment }) => segment);
  }

  // Preserve every character so rendered text is unchanged. This fallback intentionally
  // favors slightly smaller chunks when a browser has no sentence segmenter.
  const segments = [];
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (!".!?".includes(text[i])) continue;
    let end = i + 1;
    while (end < text.length && "\"'”’)]}".includes(text[end])) end += 1;
    if (end < text.length && !/\s/.test(text[end])) continue;
    while (end < text.length && /\s/.test(text[end])) end += 1;
    segments.push(text.slice(start, end));
    start = end;
    i = end - 1;
  }
  if (start < text.length) segments.push(text.slice(start));
  return segments.length ? segments : [text];
}

export function splitNarrationChunks(text) {
  const sentences = sentenceSegments(text);
  const chunks = [];
  let current = "";
  let sentenceCount = 0;

  const flush = () => {
    if (current) chunks.push(current);
    current = "";
    sentenceCount = 0;
  };

  sentences.forEach((sentence) => {
    if (
      current
      && (
        sentenceCount >= MAX_SENTENCES_PER_CHUNK
        || current.trim().length >= SHORT_CHUNK_CHARS
      )
    ) {
      flush();
    }
    current += sentence;
    sentenceCount += 1;
  });
  flush();

  return chunks.length ? chunks : (text ? [text] : []);
}

function sentenceGroupWeight(text) {
  const spokenCharacters = Array.from((text || "").replace(/\s/g, "")).length;
  const longPauses = ((text || "").match(/[.!?]/g) || []).length;
  const shortPauses = ((text || "").match(/[,;:]/g) || []).length;
  return Math.max(1, spokenCharacters + (longPauses * 7) + (shortPauses * 3));
}

function addParagraph(chunks, paragraphText, sourceIndex) {
  const paragraphChunks = splitNarrationChunks(paragraphText);
  const prepared = paragraphChunks.map((text, localIndex) => ({
    index: chunks.length + localIndex,
    sourceIndex,
    text,
    weight: sentenceGroupWeight(text),
  }));
  chunks.push(...prepared);
  return prepared;
}

export function buildPlainNarrationGuide(content) {
  const chunks = [];
  const paragraphs = (content || "")
    .split(/\n\s*\n/)
    .map((paragraph, sourceIndex) => ({ sourceIndex, text: paragraph }))
    .filter(paragraph => paragraph.text.trim())
    .map(paragraph => ({
      ...paragraph,
      chunks: addParagraph(chunks, paragraph.text, paragraph.sourceIndex),
    }));
  return { kind: "plain", chunks, paragraphs };
}

function chunkRanges(text, createChunk) {
  let offset = 0;
  return splitNarrationChunks(text).map((chunkText) => {
    const range = {
      start: offset,
      end: offset + chunkText.length,
      chunk: createChunk(chunkText),
    };
    offset = range.end;
    return range;
  });
}

function narrationBlockFor(textNode) {
  const parent = textNode.parentElement;
  if (!parent || parent.closest("script, style, noscript, svg")) return null;
  return parent.closest(RICH_NARRATION_BLOCKS);
}

export function buildRichNarrationGuide(html, content = "") {
  if (!html || typeof document === "undefined") {
    return { kind: "rich", html: html || "", chunks: [] };
  }

  const template = document.createElement("template");
  template.innerHTML = html;
  const nodesByBlock = new Map();
  const walker = document.createTreeWalker(template.content, 4);
  let textNode = walker.nextNode();
  while (textNode) {
    const block = narrationBlockFor(textNode);
    if (block && textNode.data) {
      if (!nodesByBlock.has(block)) nodesByBlock.set(block, []);
      nodesByBlock.get(block).push(textNode);
    }
    textNode = walker.nextNode();
  }

  const chunks = [];
  const sourceIndexes = (content || "")
    .split(/\n\s*\n/)
    .map((text, sourceIndex) => ({ text, sourceIndex }))
    .filter(paragraph => paragraph.text.trim())
    .map(paragraph => paragraph.sourceIndex);
  let visualParagraphIndex = 0;
  nodesByBlock.forEach((textNodes) => {
    const paragraphText = textNodes.map(node => node.data).join("");
    if (!paragraphText.trim()) return;
    const sourceIndex = sourceIndexes[visualParagraphIndex] ?? visualParagraphIndex;
    visualParagraphIndex += 1;

    const ranges = chunkRanges(paragraphText, (text) => {
      const chunk = {
        index: chunks.length,
        sourceIndex,
        text,
        weight: sentenceGroupWeight(text),
      };
      chunks.push(chunk);
      return chunk;
    });

    let nodeStart = 0;
    textNodes.forEach((node) => {
      const nodeEnd = nodeStart + node.data.length;
      const fragment = document.createDocumentFragment();
      ranges.forEach((range) => {
        const start = Math.max(nodeStart, range.start);
        const end = Math.min(nodeEnd, range.end);
        if (start >= end) return;
        const span = document.createElement("span");
        span.dataset.narrationChunk = String(range.chunk.index);
        span.textContent = node.data.slice(start - nodeStart, end - nodeStart);
        fragment.appendChild(span);
      });
      node.replaceWith(fragment);
      nodeStart = nodeEnd;
    });
  });

  return { kind: "rich", html: template.innerHTML, chunks };
}

export function activeNarrationChunk(chunks, currentTime, timingManifest) {
  if (
    !chunks || !chunks.length || !Number.isFinite(currentTime) || currentTime < 0
    || !timingManifest || timingManifest.version !== 1
    || !Number.isFinite(timingManifest.duration_ms) || timingManifest.duration_ms <= 0
    || !Array.isArray(timingManifest.paragraphs)
  ) return null;
  const manifestTime = Math.min(currentTime * 1000, timingManifest.duration_ms);
  const timedParagraph = timingManifest.paragraphs.find((paragraph, index, all) => (
    manifestTime >= paragraph.start_ms
    && (
      manifestTime < paragraph.end_ms
      || (index === all.length - 1 && manifestTime <= paragraph.end_ms)
    )
  ));
  if (!timedParagraph || timedParagraph.source_index == null) return null;

  const paragraphChunks = chunks.filter(
    chunk => chunk.sourceIndex === timedParagraph.source_index,
  );
  if (!paragraphChunks.length) return null;
  const speechDuration = Math.max(
    1, timedParagraph.speech_end_ms - timedParagraph.start_ms,
  );
  const paragraphProgress = Math.min(
    1, Math.max(0, (manifestTime - timedParagraph.start_ms) / speechDuration),
  );
  const totalWeight = paragraphChunks.reduce((sum, chunk) => sum + chunk.weight, 0);
  if (totalWeight <= 0) return null;
  const position = paragraphProgress * totalWeight;
  let elapsed = 0;
  for (const chunk of paragraphChunks) {
    elapsed += chunk.weight;
    if (position < elapsed) return chunk.index;
  }
  return paragraphChunks[paragraphChunks.length - 1].index;
}
