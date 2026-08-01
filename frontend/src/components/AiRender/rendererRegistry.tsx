import { lazy, Suspense, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../../api/client";
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

function WebSearchResults({ uiHint }: AiRenderProps) {
  const items = recordsFromHint(uiHint)
    .map((item) => ({
      url: asString(item.url),
      title: asString(item.title),
      snippet: asString(item.snippet),
      provider: asString(item.provider),
    }))
    .filter((item) => /^https?:\/\//i.test(item.url));
  return (
    <div className="ai-render-search ai-render-web-search">
      {items.length === 0 && <p className="ai-render-muted">供应商未返回可验证的网页来源。</p>}
      {items.map((item, index) => (
        <article key={item.url}>
          <header>
            <a href={item.url} target="_blank" rel="noreferrer noopener">
              {item.title || item.url}
            </a>
            <span>{item.provider || `来源 ${index + 1}`}</span>
          </header>
          {item.snippet && <p>{item.snippet}</p>}
          <small>{item.url}</small>
        </article>
      ))}
    </div>
  );
}

function normalizeSeverity(value: unknown) {
  const severity = asString(value, "notice");
  if (severity === "critical" || severity === "potential" || severity === "notice") return severity;
  return "notice";
}

const ISSUE_SEVERITY_LABELS: Record<string, string> = {
  critical: "明确冲突",
  potential: "可能冲突",
  notice: "建议复核",
};

function IssueList({ uiHint, metadata }: AiRenderProps) {
  const review = metadata ?? {};
  const usage = review.llm_usage && typeof review.llm_usage === "object" && !Array.isArray(review.llm_usage)
    ? review.llm_usage as Record<string, unknown>
    : {};
  const reviewedPaths = Array.isArray(review.reviewed_paths)
    ? review.reviewed_paths.filter((path): path is string => typeof path === "string" && Boolean(path))
    : [];
  const inputTokens = asNumber(usage.input_tokens);
  const outputTokens = asNumber(usage.output_tokens);
  const totalTokens = asNumber(usage.total_tokens);
  const mode = asString(review.mode);
  const modeLabel = asString(review.mode_label, mode === "rules" ? "保守规则" : "未知模式");
  const model = asString(review.llm_model);
  const provider = asString(review.llm_provider);
  const presetId = asString(review.llm_preset_id);
  const relatedChunks = asNumber(review.related_chunks) ?? 0;
  const items = recordsFromHint(uiHint).map((item) => ({
    severity: normalizeSeverity(item.severity),
    title: asString(item.title, "一致性提示"),
    detail: asString(item.detail),
    suggestion: asString(item.suggestion),
    path: asString(item.path),
    snippet: asString(item.snippet),
    newSnippet: asString(item.new_snippet),
    existingSnippet: asString(item.existing_snippet, asString(item.snippet)),
    score: formatScore(item.score),
  }));
  return (
    <div className="ai-render-issues">
      <div className="ai-render-review-summary">
        <div>
          <span>审查模式</span>
          <strong>{modeLabel}</strong>
        </div>
        <div>
          <span>审查模型</span>
          <strong>{model || "未调用模型"}</strong>
          {(provider || presetId) && <small>{[provider, presetId && `预设 ${presetId}`].filter(Boolean).join(" · ")}</small>}
        </div>
        <div>
          <span>Token</span>
          <strong>{totalTokens === null ? "0" : totalTokens.toLocaleString()}</strong>
          {(inputTokens !== null || outputTokens !== null) && (
            <small>输入 {inputTokens ?? 0} · 输出 {outputTokens ?? 0}</small>
          )}
        </div>
        <div>
          <span>审查范围</span>
          <strong>{reviewedPaths.length} 个文件</strong>
          <small>{relatedChunks} 个片段</small>
        </div>
      </div>
      {reviewedPaths.length > 0 && (
        <details className="ai-render-review-scope">
          <summary>查看审查文件</summary>
          <ul>
            {reviewedPaths.map((path) => <li key={path}>{path}</li>)}
          </ul>
        </details>
      )}
      {mode === "rules_fallback" && (
        <p className="ai-render-review-warning">模型返回格式无法解析，本次结果来自保守规则降级。</p>
      )}
      {items.length === 0 && <p className="ai-render-muted">未发现明确的一致性冲突。</p>}
      {items.map((item, index) => {
        return (
          <article className={`ai-render-issue ai-render-issue--${item.severity}`} key={`${item.path || "unknown"}-${index}`}>
            <header>
              <strong>{item.title}</strong>
              <span>{ISSUE_SEVERITY_LABELS[item.severity] || item.severity}</span>
            </header>
            {item.detail && <p>{item.detail}</p>}
            {(item.newSnippet || item.existingSnippet) && (
              <div className="ai-render-issue-evidence">
                {item.newSnippet && (
                  <div>
                    <span>新内容</span>
                    <blockquote>{item.newSnippet}</blockquote>
                  </div>
                )}
                {item.existingSnippet && (
                  <div>
                    <span>已有设定</span>
                    <blockquote>{item.existingSnippet}</blockquote>
                  </div>
                )}
              </div>
            )}
            {item.suggestion && <p className="ai-render-issue-suggestion">{item.suggestion}</p>}
            {item.path && <small>{item.path}{item.score ? ` · ${item.score}` : ""}</small>}
            {!item.existingSnippet && item.snippet && <blockquote>{item.snippet}</blockquote>}
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

const FORESHADOW_STATUS_LABELS: Record<string, string> = {
  planned: "计划埋设",
  planted: "已埋下",
  developing: "推进中",
  paid_off: "已回收",
  abandoned: "已废弃",
};

const FORESHADOW_IMPORTANCE_LABELS: Record<string, string> = {
  minor: "轻量",
  medium: "普通",
  major: "关键",
};

function ForeshadowList({ uiHint }: AiRenderProps) {
  const data = hintData(uiHint);
  const rawItems = Array.isArray(data.items) ? data.items : [];
  const items = rawItems.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  const mode = asString(data.mode);
  const activeCount = asNumber(data.active_count);
  return (
    <div className="ai-render-foreshadows">
      <div className="ai-render-foreshadows-meta">
        <span>{mode === "matched" ? "相关伏笔" : "未回收伏笔"}</span>
        {activeCount !== null && <small>{activeCount} 条未回收</small>}
      </div>
      {items.length === 0 && <p className="ai-render-muted">当前没有可显示的伏笔记录。</p>}
      {items.map((item, index) => {
        const reasons = Array.isArray(item.reasons) ? item.reasons.filter(Boolean).map(String) : [];
        const tags = Array.isArray(item.tags) ? item.tags.filter(Boolean).map(String) : [];
        const status = asString(item.status, "planned");
        const importance = asString(item.importance, "medium");
        return (
          <article className={`ai-render-foreshadow ai-render-foreshadow--${importance}`} key={`${asString(item.id, "foreshadow")}-${index}`}>
            <header>
              <strong>{asString(item.title, "未命名伏笔")}</strong>
              <span>{FORESHADOW_STATUS_LABELS[status] || status} · {FORESHADOW_IMPORTANCE_LABELS[importance] || importance}</span>
            </header>
            {asString(item.summary) && <p>{asString(item.summary)}</p>}
            <div className="ai-render-foreshadow-links">
              {asString(item.plant_chapter) && <small>埋设：{asString(item.plant_chapter)}</small>}
              {asString(item.payoff_chapter) && <small>回收：{asString(item.payoff_chapter)}</small>}
              {tags.length > 0 && <small>标签：{tags.join("、")}</small>}
            </div>
            {asString(item.action) && <div className="ai-render-foreshadow-action">建议：{asString(item.action)}</div>}
            {reasons.length > 0 && <div className="ai-render-foreshadow-reasons">命中：{reasons.join("；")}</div>}
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

type ChangeSetStatus = "pending" | "applied" | "discarded";

interface ChangeSetFileChange {
  path: string;
  operation: "write" | "delete";
  diff: string;
  reason?: string;
  old_length?: number;
  new_length?: number;
  source_operations?: string[];
}

interface ChangeSetData {
  id: string;
  title?: string;
  summary?: string;
  status?: ChangeSetStatus;
  project_path?: string;
  changes?: ChangeSetFileChange[];
  agent_resumed?: boolean;
  agent_waiting?: boolean;
  deferred?: boolean;
  warnings?: string[];
  foreshadow_actions?: Array<{
    action?: string;
    title?: string;
    status?: string;
    evidence?: string;
  }>;
  fact_records?: Array<{
    id?: string;
    category?: string;
    subject?: string;
    predicate?: string;
    value?: string;
    certainty?: string;
    evidence?: string;
    time?: string;
    tags?: string[];
  }>;
  foreshadow_verification?: Array<{
    action?: string;
    foreshadow_id?: string;
    status?: "verified" | "review" | string;
    evidence_match?: boolean;
    issues?: string[];
  }>;
  file_verification?: {
    status?: "verified" | "review" | string;
    verified?: number;
    total?: number;
    issues?: string[];
    files?: Array<{
      path?: string;
      operation?: string;
      verified?: boolean;
      issue?: string;
    }>;
  } | null;
}

const CHANGESET_STATUS_LABELS: Record<ChangeSetStatus, string> = {
  pending: "等待确认",
  applied: "已应用",
  discarded: "已丢弃",
};

const FORESHADOW_ACTION_LABELS: Record<string, string> = {
  plant: "新埋",
  advance: "推进",
  payoff: "回收",
};

const FACT_CATEGORY_LABELS: Record<string, string> = {
  identity: "身份",
  state: "状态",
  relationship: "关系",
  location: "位置",
  possession: "持有物",
  timeline: "时间",
  world_rule: "世界规则",
  other: "其他",
};

const FACT_CERTAINTY_LABELS: Record<string, string> = {
  confirmed: "叙事确认",
  reported: "角色转述",
  uncertain: "仍存疑",
};

const FILE_OPERATION_LABELS: Record<string, string> = {
  write: "完整写入",
  replace_text: "局部替换",
  append_text: "追加内容",
  prepend_text: "前置内容",
  delete: "删除",
  delete_directory: "目录清理",
};

function diffLineClass(line: string) {
  if (line.startsWith("+++") || line.startsWith("---")) return "ai-render-diff-line--meta";
  if (line.startsWith("@@")) return "ai-render-diff-line--hunk";
  if (line.startsWith("+")) return "ai-render-diff-line--add";
  if (line.startsWith("-")) return "ai-render-diff-line--remove";
  return "";
}

function ChangeSetProposal({ uiHint, onWorkspaceChanged }: AiRenderProps) {
  const data = hintData(uiHint) as Partial<ChangeSetData>;
  const id = asString(data.id);
  const title = asString(data.title, "待确认文件改动");
  const summary = asString(data.summary);
  const projectPath = asString(data.project_path);
  const changes = Array.isArray(data.changes) ? data.changes : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  const foreshadowActions = Array.isArray(data.foreshadow_actions) ? data.foreshadow_actions : [];
  const factRecords = Array.isArray(data.fact_records) ? data.fact_records : [];
  const foreshadowVerification = Array.isArray(data.foreshadow_verification) ? data.foreshadow_verification : [];
  const [status, setStatus] = useState<ChangeSetStatus>((data.status as ChangeSetStatus) || "pending");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [actionNote, setActionNote] = useState("");
  const [agentWaiting, setAgentWaiting] = useState(Boolean(data.agent_waiting));
  const [fileVerification, setFileVerification] = useState(data.file_verification ?? null);

  const canAct = Boolean(id && projectPath && status === "pending" && !busy);
  const canDefer = Boolean(canAct && agentWaiting);

  useEffect(() => {
    if (data.status) setStatus(data.status);
    if (typeof data.agent_waiting === "boolean") setAgentWaiting(data.agent_waiting);
    if (data.file_verification !== undefined) setFileVerification(data.file_verification ?? null);
  }, [data.agent_waiting, data.file_verification, data.status]);

  useEffect(() => {
    if (!id || !projectPath) return;
    let cancelled = false;
    const params = new URLSearchParams({ project_path: projectPath });
    void api
      .get<ChangeSetData>(`/change-sets/${encodeURIComponent(id)}?${params.toString()}`)
      .then((result) => {
        if (cancelled) return;
        if (result.status) setStatus(result.status);
        setAgentWaiting(Boolean(result.agent_waiting));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, projectPath]);

  async function applyAll() {
    if (!canAct) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<ChangeSetData>(`/change-sets/${encodeURIComponent(id)}/apply`, {
        project_path: projectPath,
      });
      setStatus((result.status as ChangeSetStatus) || "applied");
      setAgentWaiting(false);
      setFileVerification(result.file_verification ?? null);
      setActionNote(result.agent_resumed ? "改动已应用，Agent 正在继续验证。" : "改动已应用。原 Agent 已结束或服务曾重启，可发送新消息继续验证。");
      await onWorkspaceChanged?.({
        changeSetId: id,
        changes: (result.changes ?? changes).map((change) => ({ path: change.path, operation: change.operation })),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (!canAct) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<ChangeSetData>(`/change-sets/${encodeURIComponent(id)}/discard`, {
        project_path: projectPath,
      });
      setStatus((result.status as ChangeSetStatus) || "discarded");
      setAgentWaiting(false);
      setActionNote(result.agent_resumed ? "改动已丢弃，Agent 正在整理结果。" : "改动已丢弃。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function defer() {
    if (!canDefer) return;
    setBusy(true);
    setError("");
    try {
      await api.post<ChangeSetData>(`/change-sets/${encodeURIComponent(id)}/defer`, {
        project_path: projectPath,
      });
      setAgentWaiting(false);
      setActionNote("已留待稍后处理，Agent 正在结束本轮；改动包仍可继续应用或丢弃。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`ai-render-changeset ai-render-changeset--${status}`}>
      <header className="ai-render-changeset-head">
        <div>
          <span className="ai-render-changeset-kicker">文件改动包</span>
          <h4>{title}</h4>
          {summary && <p>{summary}</p>}
        </div>
        <span className="ai-render-changeset-status">{CHANGESET_STATUS_LABELS[status]}</span>
      </header>

      {warnings.length > 0 && (
        <details className="ai-render-changeset-warnings">
          <summary>
            <strong>已跳过无效伏笔动作</strong>
            <span>{warnings.length} 条</span>
          </summary>
          <ul>
            {warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        </details>
      )}

      {foreshadowActions.length > 0 && (
        <div className="ai-render-changeset-foreshadows">
          <strong>本章伏笔动作</strong>
          {foreshadowActions.map((item, index) => (
            <div key={`${String(item.title || "foreshadow")}-${index}`}>
              <span>{FORESHADOW_ACTION_LABELS[item.action || ""] || item.action || "变更"}</span>
              <b>{item.title || "未命名伏笔"}</b>
              {item.evidence && <small>{item.evidence}</small>}
            </div>
          ))}
          {foreshadowVerification.length > 0 && (
            <div className="ai-render-changeset-foreshadow-verification">
              <strong>应用后证据复核</strong>
              {foreshadowVerification.map((item, index) => {
                const verified = item.status === "verified";
                const issues = Array.isArray(item.issues) ? item.issues.filter(Boolean) : [];
                return (
                  <div key={`${String(item.foreshadow_id || item.action || "verification")}-${index}`}>
                    <span className={verified ? "ai-render-foreshadow-verified" : "ai-render-foreshadow-review"}>
                      {verified ? "已核对" : "待复核"}
                    </span>
                    {!verified && <small>{issues.length ? issues.join("；") : "证据需要人工确认"}</small>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {factRecords.length > 0 && (
        <details className="ai-render-changeset-facts" open={factRecords.length <= 4}>
          <summary>
            <strong>本章长期事实</strong>
            <span>{factRecords.length} 条</span>
          </summary>
          <div className="ai-render-changeset-fact-list">
            {factRecords.map((fact, index) => {
              const tags = Array.isArray(fact.tags) ? fact.tags.filter(Boolean) : [];
              const category = fact.category || "other";
              const certainty = fact.certainty || "confirmed";
              return (
                <div className="ai-render-changeset-fact" key={`${fact.id || fact.subject || "fact"}-${index}`}>
                  <header>
                    <span>{FACT_CATEGORY_LABELS[category] || category}</span>
                    <strong>{fact.subject || "未知主体"}</strong>
                    <small>{FACT_CERTAINTY_LABELS[certainty] || certainty}</small>
                  </header>
                  <p><b>{fact.predicate || "属性"}</b>：{fact.value || "未填写"}</p>
                  {fact.evidence && <blockquote>{fact.evidence}</blockquote>}
                  {(fact.time || tags.length > 0) && (
                    <footer>
                      {fact.time && <span>时间：{fact.time}</span>}
                      {tags.length > 0 && <span>标签：{tags.join("、")}</span>}
                    </footer>
                  )}
                </div>
              );
            })}
          </div>
        </details>
      )}

      {fileVerification && (
        <div className={`ai-render-file-verification ai-render-file-verification--${fileVerification.status === "verified" ? "verified" : "review"}`}>
          <strong>{fileVerification.status === "verified" ? "文件写入已核验" : "文件写入待复核"}</strong>
          <span>{fileVerification.verified ?? 0}/{fileVerification.total ?? changes.length} 个文件通过</span>
          {Array.isArray(fileVerification.issues) && fileVerification.issues.length > 0 && (
            <small>{fileVerification.issues.join("；")}</small>
          )}
        </div>
      )}

      <div className="ai-render-changeset-files">
        {changes.map((change, index) => {
          const diffLines = asString(change.diff).split("\n");
          const sourceOperations = Array.isArray(change.source_operations) ? change.source_operations : [];
          const operationLabel = sourceOperations.length
            ? sourceOperations.map((operation) => FILE_OPERATION_LABELS[operation] || operation).join(" + ")
            : change.operation === "delete" ? "删除" : "写入";
          return (
            <details key={`${change.path}-${index}`} open={index === 0 && changes.length <= 3}>
              <summary>
                <span>{change.path}</span>
                <small>{operationLabel} · {diffLines.length} 行差异</small>
              </summary>
              {change.reason && <p className="ai-render-muted">{change.reason}</p>}
              <pre className="ai-render-diff">
                {diffLines.map((line, lineIndex) => (
                  <span className={diffLineClass(line)} key={`${lineIndex}-${line}`}>
                    {line || " "}
                  </span>
                ))}
              </pre>
            </details>
          );
        })}
        {changes.length === 0 && <p className="ai-render-muted">没有可显示的文件差异。</p>}
      </div>

      {error && <p className="ai-render-changeset-error">{error}</p>}
      {actionNote && <p className="ai-render-muted">{actionNote}</p>}
      <footer className="ai-render-changeset-actions">
        <button type="button" onClick={applyAll} disabled={!canAct}>
          {busy ? "处理中..." : "应用全部"}
        </button>
        <button type="button" className="ai-render-button-secondary" onClick={discard} disabled={!canAct}>
          丢弃
        </button>
        {agentWaiting && (
          <button type="button" className="ai-render-button-secondary" onClick={defer} disabled={!canDefer}>
            稍后处理
          </button>
        )}
      </footer>
    </section>
  );
}

export type AiRenderer = (props: AiRenderProps) => ReactNode;

export const RENDERER_REGISTRY: Record<string, AiRenderer> = {
  "stream:editor": MarkdownPreview,
  "document:worldview": MarkdownPreview,
  "list:search_results": SearchResults,
  "list:web_sources": WebSearchResults,
  "list:issues": IssueList,
  "card:character": CharacterCard,
  "list:outline_chapters": OutlineChapters,
  "list:foreshadows": ForeshadowList,
  "changeset:proposal": ChangeSetProposal,
};

export function rendererFor(type: string) {
  return RENDERER_REGISTRY[type] ?? null;
}
