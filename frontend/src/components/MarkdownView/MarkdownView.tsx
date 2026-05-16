import type { ReactNode } from "react";
import "./MarkdownView.css";

interface MarkdownViewProps {
  content: string;
}

interface ListItem {
  content: string;
  checked?: boolean;
  children: ListBlock[];
}

interface ListBlock {
  type: "list";
  ordered: boolean;
  start: number;
  items: ListItem[];
}

type Block =
  | { type: "code"; language: string; content: string }
  | { type: "heading"; level: number; content: string }
  | { type: "quote"; content: string }
  | { type: "hr" }
  | { type: "table"; headers: string[]; rows: string[][] }
  | ListBlock
  | { type: "paragraph"; content: string };

interface ListMarker {
  indent: number;
  ordered: boolean;
  start: number;
  checked?: boolean;
  content: string;
}

function isSafeHref(href: string) {
  return /^(https?:|mailto:|\/|#)/i.test(href);
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let buffer = "";
  let index = 0;

  const flush = () => {
    if (!buffer) return;
    nodes.push(buffer);
    buffer = "";
  };

  while (index < text.length) {
    const char = text[index];
    const next = text[index + 1];

    if (char === "\\" && next) {
      buffer += next;
      index += 2;
      continue;
    }

    if (char === "`") {
      const end = text.indexOf("`", index + 1);
      if (end > index + 1) {
        flush();
        nodes.push(<code key={`code-${index}`}>{text.slice(index + 1, end)}</code>);
        index = end + 1;
        continue;
      }
    }

    if (text.startsWith("**", index)) {
      const end = text.indexOf("**", index + 2);
      if (end > index + 2) {
        flush();
        nodes.push(<strong key={`strong-${index}`}>{renderInline(text.slice(index + 2, end))}</strong>);
        index = end + 2;
        continue;
      }
    }

    if (char === "*") {
      const end = text.indexOf("*", index + 1);
      if (end > index + 1) {
        flush();
        nodes.push(<em key={`em-${index}`}>{renderInline(text.slice(index + 1, end))}</em>);
        index = end + 1;
        continue;
      }
    }

    if (char === "[") {
      const labelEnd = text.indexOf("](", index);
      const hrefEnd = labelEnd >= 0 ? text.indexOf(")", labelEnd + 2) : -1;
      if (labelEnd > index && hrefEnd > labelEnd) {
        const label = text.slice(index + 1, labelEnd);
        const href = text.slice(labelEnd + 2, hrefEnd);
        if (isSafeHref(href)) {
          flush();
          nodes.push(
            <a key={`link-${index}`} href={href} target="_blank" rel="noreferrer">
              {renderInline(label)}
            </a>,
          );
          index = hrefEnd + 1;
          continue;
        }
      }
    }

    buffer += char;
    index += 1;
  }

  flush();
  return nodes;
}

function isTableRow(line: string) {
  return /^\s*\|.+\|\s*$/.test(line);
}

function isTableDivider(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isHorizontalRule(line: string) {
  return /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
}

function indentWidth(value: string) {
  let width = 0;
  for (const char of value) {
    if (char === " ") width += 1;
    else if (char === "\t") width += 4;
    else break;
  }
  return width;
}

function listMarkerMatch(line: string): ListMarker | null {
  const match = /^(\s*)((\d+)[.)、]|[-*+])\s+(?:\[([ xX])\]\s+)?(.*)$/.exec(line);
  if (!match) return null;
  const start = match[3] ? Number(match[3]) : 1;
  return {
    indent: indentWidth(match[1] ?? ""),
    ordered: Boolean(match[3]),
    start: Number.isFinite(start) ? start : 1,
    checked: match[4] ? match[4].toLowerCase() === "x" : undefined,
    content: match[5] ?? "",
  };
}

function nextNonBlankIndex(lines: string[], index: number) {
  let next = index;
  while (next < lines.length && !lines[next].trim()) next += 1;
  return next;
}

function shouldAttachSameIndentChild(parent: ListItem, parentOrdered: boolean, marker: ListMarker) {
  if (!parentOrdered || marker.ordered) return false;
  return /[:：]\s*$/.test(parent.content);
}

function parseList(lines: string[], startIndex: number): { block: ListBlock; nextIndex: number } {
  const first = listMarkerMatch(lines[startIndex]);
  if (!first) {
    return { block: { type: "list", ordered: false, start: 1, items: [] }, nextIndex: startIndex + 1 };
  }

  const listIndent = first.indent;
  const ordered = first.ordered;
  const block: ListBlock = { type: "list", ordered, start: first.start, items: [] };
  let index = startIndex;

  while (index < lines.length) {
    const marker = listMarkerMatch(lines[index]);
    if (!marker || marker.indent !== listIndent || marker.ordered !== ordered) break;

    const item: ListItem = {
      content: marker.content,
      checked: marker.checked,
      children: [],
    };
    block.items.push(item);
    index += 1;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        const nextIndex = nextNonBlankIndex(lines, index);
        const nextMarker = nextIndex < lines.length ? listMarkerMatch(lines[nextIndex]) : null;
        if (nextMarker && nextMarker.indent >= listIndent) {
          index += 1;
          continue;
        }
        break;
      }

      const nextMarker = listMarkerMatch(line);
      if (nextMarker) {
        if (nextMarker.indent > listIndent) {
          const child = parseList(lines, index);
          item.children.push(child.block);
          index = child.nextIndex;
          continue;
        }

        if (
          nextMarker.indent === listIndent &&
          nextMarker.ordered !== ordered &&
          shouldAttachSameIndentChild(item, ordered, nextMarker)
        ) {
          const child = parseList(lines, index);
          item.children.push(child.block);
          index = child.nextIndex;
          continue;
        }

        break;
      }

      const continuationIndent = indentWidth(line);
      if (continuationIndent > listIndent) {
        item.content = `${item.content}${item.content ? "\n" : ""}${line.trim()}`;
        index += 1;
        continue;
      }

      break;
    }
  }

  return { block, nextIndex: index };
}

function parseBlocks(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = /^```(\S*)\s*$/.exec(line);
    if (fence) {
      const language = fence[1] ?? "";
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: "code", language, content: code.join("\n") });
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, content: heading[2] });
      index += 1;
      continue;
    }

    if (isHorizontalRule(line)) {
      blocks.push({ type: "hr" });
      index += 1;
      continue;
    }

    if (isTableRow(line) && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headers = splitTableRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", content: quote.join("\n") });
      continue;
    }

    if (listMarkerMatch(line)) {
      const result = parseList(lines, index);
      blocks.push(result.block);
      index = result.nextIndex;
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^```/.test(lines[index]) &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !isHorizontalRule(lines[index]) &&
      !(isTableRow(lines[index]) && index + 1 < lines.length && isTableDivider(lines[index + 1])) &&
      !/^>\s?/.test(lines[index]) &&
      !listMarkerMatch(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", content: paragraph.join("\n") });
  }

  return normalizeListBlocks(blocks);
}

function normalizeListBlocks(blocks: Block[]): Block[] {
  const normalized: Block[] = [];
  for (const block of blocks) {
    const previous = normalized[normalized.length - 1];
    if (block.type === "list" && previous?.type === "list") {
      const lastPreviousItem = previous.items[previous.items.length - 1];
      if (!previous.ordered && !block.ordered) {
        previous.items.push(...block.items);
        continue;
      }
      if (previous.ordered && block.ordered) {
        previous.items.push(...block.items);
        continue;
      }
      if (previous.ordered && !block.ordered && lastPreviousItem && /[:：]\s*$/.test(lastPreviousItem.content)) {
        lastPreviousItem.children.push(block);
        continue;
      }
    }
    normalized.push(block);
  }
  return normalized;
}

function renderList(block: ListBlock, key?: number | string): ReactNode {
  const Tag = block.ordered ? "ol" : "ul";
  const hasTasks = block.items.some((item) => typeof item.checked === "boolean");
  return (
    <Tag
      key={key}
      start={block.ordered && block.start !== 1 ? block.start : undefined}
      className={hasTasks ? "markdown-view-task-list" : undefined}
    >
      {block.items.map((item, index) => (
        <li key={index} className={item.checked ? "is-checked" : ""}>
          {typeof item.checked === "boolean" ? (
            <label>
              <input type="checkbox" checked={item.checked} readOnly />
              <span className="markdown-view-list-text">{renderInline(item.content)}</span>
            </label>
          ) : (
            <span className="markdown-view-list-text">{renderInline(item.content)}</span>
          )}
          {item.children.map((child, childIndex) => renderList(child, childIndex))}
        </li>
      ))}
    </Tag>
  );
}

export default function MarkdownView({ content }: MarkdownViewProps) {
  const blocks = parseBlocks(content);

  return (
    <div className="markdown-view">
      {blocks.map((block, index) => {
        if (block.type === "code") {
          return (
            <pre key={index}>
              {block.language && <span className="markdown-view-code-lang">{block.language}</span>}
              <code>{block.content}</code>
            </pre>
          );
        }
        if (block.type === "heading") {
          const Tag = `h${block.level}` as "h1" | "h2" | "h3" | "h4";
          return <Tag key={index}>{renderInline(block.content)}</Tag>;
        }
        if (block.type === "quote") {
          return <blockquote key={index}>{renderInline(block.content)}</blockquote>;
        }
        if (block.type === "hr") {
          return <hr key={index} />;
        }
        if (block.type === "table") {
          return (
            <div className="markdown-view-table-wrap" key={index}>
              <table>
                <thead>
                  <tr>
                    {block.headers.map((header, cellIndex) => <th key={cellIndex}>{renderInline(header)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {block.headers.map((_, cellIndex) => <td key={cellIndex}>{renderInline(row[cellIndex] ?? "")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === "list") {
          return renderList(block, index);
        }
        return <p key={index}>{renderInline(block.content)}</p>;
      })}
    </div>
  );
}
