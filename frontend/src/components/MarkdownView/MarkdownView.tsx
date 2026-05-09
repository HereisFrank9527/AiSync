import type { ReactNode } from "react";
import "./MarkdownView.css";

interface MarkdownViewProps {
  content: string;
}

type Block =
  | { type: "code"; language: string; content: string }
  | { type: "heading"; level: number; content: string }
  | { type: "quote"; content: string }
  | { type: "hr" }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "task"; items: { checked: boolean; content: string }[] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "paragraph"; content: string };

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

function taskListMatch(line: string) {
  return /^\s*[-*]\s+\[([ xX])\]\s+(.+)$/.exec(line);
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

    if (taskListMatch(line)) {
      const items: { checked: boolean; content: string }[] = [];
      while (index < lines.length) {
        const item = taskListMatch(lines[index]);
        if (!item) break;
        items.push({ checked: item[1].toLowerCase() === "x", content: item[2] });
        index += 1;
      }
      blocks.push({ type: "task", items });
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

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push({ type: "ol", items });
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
      !taskListMatch(lines[index]) &&
      !/^>\s?/.test(lines[index]) &&
      !/^\s*[-*]\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", content: paragraph.join("\n") });
  }

  return blocks;
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
        if (block.type === "task") {
          return (
            <ul key={index} className="markdown-view-task-list">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex} className={item.checked ? "is-checked" : ""}>
                  <label>
                    <input type="checkbox" checked={item.checked} readOnly />
                    <span>{renderInline(item.content)}</span>
                  </label>
                </li>
              ))}
            </ul>
          );
        }
        if (block.type === "ul") {
          return <ul key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}</ul>;
        }
        if (block.type === "ol") {
          return <ol key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}</ol>;
        }
        return <p key={index}>{renderInline(block.content)}</p>;
      })}
    </div>
  );
}
