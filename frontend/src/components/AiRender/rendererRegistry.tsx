import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import type { AiRenderProps, UiHint } from "./types";

const MarkdownEditor = lazy(() => import("../MarkdownEditor"));

function hintData(uiHint: UiHint) {
  const data = uiHint?.data;
  return (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
}

function asString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function recordsFromHint(uiHint: UiHint) {
  const data = uiHint?.data;
  return Array.isArray(data)
    ? data.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function formatScore(value: unknown) {
  const score = asNumber(value);
  return score === null ? "" : score.toFixed(3);
}

function SearchResults({ uiHint }: AiRenderProps) {
  const items = recordsFromHint(uiHint)
    .map((item) => ({
      path: asString(item.path, "未知文件"),
      snippet: asString(item.snippet),
      collection: asString(item.collection),
      score: formatScore(item.score),
    }))
    .filter((item) => item.path || item.snippet);
  return (
    <div className="ai-render-search">
      {items.length === 0 && <p className="ai-render-muted">没有匹配结果。</p>}
      {items.map((item, index) => {
        return (
          <article key={`${item.path}-${index}`}>
            <header>
              <strong>{item.path}</strong>
              {(item.collection || item.score) && <span>{[item.collection, item.score].filter(Boolean).join(" · ")}</span>}
            </header>
            <p>{item.snippet}</p>
          </article>
        );
      })}
    </div>
  );
}

function normalizeSeverity(value: unknown) {
  const severity = asString(value, "notice");
  if (severity === "critical" || severity === "potential" || severity === "notice") return severity;
  return "notice";
}

function IssueList({ uiHint }: AiRenderProps) {
  const items = recordsFromHint(uiHint).map((item) => ({
    severity: normalizeSeverity(item.severity),
    title: asString(item.title, "一致性提示"),
    detail: asString(item.detail),
    suggestion: asString(item.suggestion),
    path: asString(item.path),
    snippet: asString(item.snippet),
    score: formatScore(item.score),
  }));
  return (
    <div className="ai-render-issues">
      {items.length === 0 && <p className="ai-render-muted">没有发现明显一致性问题。</p>}
      {items.map((item, index) => {
        return (
          <article className={`ai-render-issue ai-render-issue--${item.severity}`} key={`${item.path || "unknown"}-${index}`}>
            <header>
              <strong>{item.title}</strong>
              <span>{item.severity}</span>
            </header>
            {item.detail && <p>{item.detail}</p>}
            {item.suggestion && <p className="ai-render-issue-suggestion">{item.suggestion}</p>}
            {item.path && <small>{item.path}{item.score ? ` · ${item.score}` : ""}</small>}
            {item.snippet && <blockquote>{item.snippet}</blockquote>}
          </article>
        );
      })}
    </div>
  );
}

function CharacterCard({ uiHint }: AiRenderProps) {
  const data = hintData(uiHint);
  return (
    <div className="ai-render-character">
      <h4>{String(data.name ?? "未命名角色")}</h4>
      {Boolean(data.role) && <p>{String(data.role)}</p>}
      {Boolean(data.summary) && <p>{String(data.summary)}</p>}
      {Boolean(data.profile_path) && <small>{String(data.profile_path)}</small>}
    </div>
  );
}

function OutlineChapters({ content, uiHint }: AiRenderProps) {
  const data = hintData(uiHint);
  const rawItems = Array.isArray(data.items) ? data.items : [];
  const items = rawItems.length ? rawItems : [];
  if (!items.length) {
    return <pre className="ai-render-json">{String(data.content ?? content ?? "")}</pre>;
  }
  return (
    <div className="ai-render-outline">
      {items.map((item, index) => {
        const row = item as Record<string, unknown>;
        return (
          <article key={`${String(row.index ?? index)}-${String(row.title ?? index)}`}>
            <strong>{String(row.index ?? index + 1)}. {String(row.title ?? "未命名节点")}</strong>
            {Boolean(row.summary) && <p>{String(row.summary)}</p>}
          </article>
        );
      })}
    </div>
  );
}

function MarkdownPreview({ content, uiHint, compact }: AiRenderProps) {
  const data = hintData(uiHint);
  const path = data.path;
  return (
    <div className={`ai-render-editor${compact ? " ai-render-editor--compact" : ""}`}>
      {Boolean(path) && <p className="ai-render-muted">{String(path)}</p>}
      <Suspense fallback={<p className="ai-render-muted">加载编辑器…</p>}>
        <MarkdownEditor value={String(data.content ?? content ?? "")} readonly />
      </Suspense>
    </div>
  );
}

export type AiRenderer = (props: AiRenderProps) => ReactNode;

export const RENDERER_REGISTRY: Record<string, AiRenderer> = {
  "stream:editor": MarkdownPreview,
  "document:worldview": MarkdownPreview,
  "list:search_results": SearchResults,
  "list:issues": IssueList,
  "card:character": CharacterCard,
  "list:outline_chapters": OutlineChapters,
};

export function rendererFor(type: string) {
  return RENDERER_REGISTRY[type] ?? null;
}
