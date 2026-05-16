import { useEffect, useMemo, useState } from "react";
import type {
  ForeshadowItem,
  StoryChapter,
  StoryChapterMetadataUpdate,
  StoryChapters,
  StoryForeshadows,
  StoryOutline,
  ToolDescriptor,
  VectorIndexStatus,
  VectorSearchResult,
} from "../../types";
import MarkdownView from "../MarkdownView";
import "./ChapterPanel.css";

interface ChapterPanelProps {
  chapters: StoryChapters | null;
  outline: StoryOutline | null;
  foreshadows: StoryForeshadows | null;
  loading: boolean;
  saving: boolean;
  error: string;
  vectorStatus: VectorIndexStatus | null;
  vectorResults: VectorSearchResult[];
  vectorSearching: boolean;
  vectorRebuilding: boolean;
  vectorError: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onSaveDocument: (path: string, content: string) => void | Promise<unknown>;
  onSaveMetadata: (path: string, metadata: StoryChapterMetadataUpdate) => void | Promise<unknown>;
  onVectorSearch: (query: string, collections: string[], topK: number) => void | Promise<unknown>;
  onVectorRebuild: () => void | Promise<unknown>;
  onOpenTool: (tool: ToolDescriptor, initialParams?: Record<string, unknown>) => void;
  onOpenFile: (path: string) => void;
}

const STATUS_OPTIONS = [
  { value: "draft", label: "草稿" },
  { value: "writing", label: "写作中" },
  { value: "revising", label: "修订中" },
  { value: "done", label: "已完成" },
];

const FORESHADOW_STATUS_LABELS: Record<string, string> = {
  planned: "计划埋",
  planted: "已埋下",
  developing: "推进中",
  paid_off: "已回收",
  abandoned: "废弃",
};

const FORESHADOW_IMPORTANCE_LABELS: Record<string, string> = {
  minor: "轻量",
  medium: "普通",
  major: "关键",
};

function formatNumber(value: number) {
  return new Intl.NumberFormat().format(value);
}

function progressWidth(done: number, target: number) {
  if (!target) return "0%";
  return `${Math.min(Math.round((done / target) * 100), 100)}%`;
}

function chapterVectorQuery(chapter: StoryChapter) {
  const parts = [chapter.title, chapter.summary, chapter.content.slice(0, 1600)]
    .map((item) => item.trim())
    .filter(Boolean);
  return parts.join("\n\n");
}

function vectorStatusLabel(status: VectorIndexStatus | null) {
  if (!status) return "未加载";
  if (status.status === "ready") return "可用";
  if (status.status === "stale") return "需更新";
  if (status.status === "missing") return "未建立";
  if (status.status === "invalid") return "需重建";
  return status.status;
}

function foreshadowStatusLabel(value: string) {
  return FORESHADOW_STATUS_LABELS[value] ?? value;
}

function foreshadowImportanceLabel(value: string) {
  return FORESHADOW_IMPORTANCE_LABELS[value] ?? value;
}

function uniqueForeshadows(items: ForeshadowItem[]) {
  const seen = new Set<string>();
  const result: ForeshadowItem[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    result.push(item);
  }
  return result;
}

interface ExplainedForeshadow extends ForeshadowItem {
  matchReasons: string[];
  action: string;
}

function explainForeshadow(item: ForeshadowItem, active: StoryChapter, group: string): ExplainedForeshadow {
  const reasons: string[] = [];
  let action = "参考";
  if (item.payoff_chapter === active.path) {
    reasons.push("目标章节是回收章节");
    action = "优先回收";
  }
  if (item.plant_chapter === active.path) {
    reasons.push("目标章节是埋设章节");
    if (action === "参考") action = "埋设";
  }
  if (active.outline_id && item.outline_ids.includes(active.outline_id)) {
    reasons.push("关联同一大纲节点");
    if (action === "参考" && ["planted", "developing"].includes(item.status)) action = "推进";
  }
  if (item.related_files.includes(active.path)) {
    reasons.push("相关文件包含本章");
  }
  if (group && !reasons.length) reasons.push(group);
  if (item.status === "paid_off") action = "避免重复回收";
  if (item.status === "abandoned") action = "不要主动使用";
  return { ...item, matchReasons: reasons, action };
}

function ForeshadowGroup({ title, items }: { title: string; items: ExplainedForeshadow[] }) {
  return (
    <div className="chapter-foreshadow-group">
      <strong>{title}</strong>
      <div>
        {items.map((item) => (
          <article key={item.id} className={`chapter-foreshadow-item is-${item.importance}`}>
            <div>
              <span>{item.title}</span>
              <em>{foreshadowStatusLabel(item.status)} · {foreshadowImportanceLabel(item.importance)}</em>
            </div>
            {item.summary && <p>{item.summary}</p>}
            <div className="chapter-foreshadow-explain">
              <b>{item.action}</b>
              {item.matchReasons.slice(0, 3).map((reason) => <i key={reason}>{reason}</i>)}
            </div>
            {item.tags.length > 0 && <small>{item.tags.join(" / ")}</small>}
          </article>
        ))}
      </div>
    </div>
  );
}

export default function ChapterPanel({
  chapters,
  outline,
  foreshadows,
  loading,
  saving,
  error,
  vectorStatus,
  vectorResults,
  vectorSearching,
  vectorRebuilding,
  vectorError,
  tools,
  onRefresh,
  onSaveDocument,
  onSaveMetadata,
  onVectorSearch,
  onVectorRebuild,
  onOpenTool,
  onOpenFile,
}: ChapterPanelProps) {
  const writeTool = tools.find((tool) => tool.name === "write_chapter");
  const editTool = tools.find((tool) => tool.name === "edit_chapter");
  const consistencyTool = tools.find((tool) => tool.name === "consistency_check");
  const items = chapters?.items ?? [];
  const foreshadowItems = foreshadows?.items ?? [];
  const outlineItems = useMemo(() => outline?.items ?? [], [outline?.items]);
  const outlineTitleById = useMemo(() => {
    const titles = new Map<string, string>();
    outlineItems.forEach((item, index) => {
      const id = String(item.id || `outline-${index + 1}`);
      titles.set(id, String(item.title || item.raw || `节点 ${index + 1}`));
    });
    return titles;
  }, [outlineItems]);
  const [query, setQuery] = useState("");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [metadataDraft, setMetadataDraft] = useState<StoryChapterMetadataUpdate>({
    status: "draft",
    summary: "",
    target_characters: 0,
    revision: 0,
    outline_id: "",
  });
  const [editing, setEditing] = useState(false);
  const [showVectorResults, setShowVectorResults] = useState(false);
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return items;
    return items.filter((item) => `${item.path}\n${item.title}\n${item.summary}\n${item.content}`.toLowerCase().includes(normalized));
  }, [items, query]);
  const active = items.find((item) => item.path === activePath) ?? visibleItems[0] ?? null;
  const relatedForeshadows = useMemo(() => {
    if (!active) return { planting: [], payoff: [], outline: [], related: [], all: [] };
    const planting = foreshadowItems.filter((item) => item.plant_chapter === active.path);
    const payoff = foreshadowItems.filter((item) => item.payoff_chapter === active.path);
    const outlineRelated = active.outline_id
      ? foreshadowItems.filter((item) => item.outline_ids.includes(active.outline_id))
      : [];
    const fileRelated = foreshadowItems.filter((item) => item.related_files.includes(active.path));
    return {
      planting: planting.map((item) => explainForeshadow(item, active, "本章埋设")),
      payoff: payoff.map((item) => explainForeshadow(item, active, "本章回收")),
      outline: uniqueForeshadows(outlineRelated.filter((item) => !planting.includes(item) && !payoff.includes(item)))
        .map((item) => explainForeshadow(item, active, "同大纲节点")),
      related: uniqueForeshadows(fileRelated.filter((item) => !planting.includes(item) && !payoff.includes(item) && !outlineRelated.includes(item)))
        .map((item) => explainForeshadow(item, active, "相关文件")),
      all: uniqueForeshadows([...payoff, ...planting, ...outlineRelated, ...fileRelated]),
    };
  }, [active, foreshadowItems]);

  useEffect(() => {
    if (!active) {
      setDraft("");
      return;
    }
    setDraft(active.content);
    setMetadataDraft({
      status: active.status || "draft",
      summary: active.summary || "",
      target_characters: active.target_characters || 0,
      revision: active.revision || 0,
      outline_id: active.outline_id || "",
    });
    setShowVectorResults(false);
  }, [active]);

  const changed = Boolean(active && draft !== active.content);
  const metadataChanged = Boolean(active && (
    metadataDraft.status !== active.status ||
    metadataDraft.summary !== active.summary ||
    Number(metadataDraft.target_characters || 0) !== active.target_characters ||
    Number(metadataDraft.revision || 0) !== active.revision ||
    metadataDraft.outline_id !== active.outline_id
  ));
  const setMetadataField = <K extends keyof StoryChapterMetadataUpdate>(key: K, value: StoryChapterMetadataUpdate[K]) => {
    setMetadataDraft((current) => ({ ...current, [key]: value }));
  };
  const searchRelatedContext = async () => {
    if (!active) return;
    setShowVectorResults(true);
    await onVectorSearch(chapterVectorQuery(active), ["world", "characters", "plot"], 8);
  };

  return (
    <section className="chapter-panel">
      <header className="chapter-header">
        <div>
          <h2>章节管理</h2>
          <p>{chapters?.source ?? "chapters"} · {items.length} 章 · {formatNumber(chapters?.total_characters ?? 0)} 字符</p>
        </div>
        <div className="chapter-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-secondary" disabled={!editTool} onClick={() => editTool && onOpenTool(editTool)}>编辑工具</button>
          <button className="btn-primary" disabled={!writeTool} onClick={() => writeTool && onOpenTool(writeTool)}>写新章节</button>
        </div>
      </header>

      {loading && <p className="chapter-muted">加载章节中…</p>}
      {error && <p className="chapter-error">{error}</p>}

      {!loading && !error && (
        <div className="chapter-layout">
          <aside className="chapter-list">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索章节"
            />
            {visibleItems.length === 0 && <p className="chapter-muted">没有匹配章节</p>}
            {visibleItems.map((item) => (
              <button
                key={item.path}
                className={`chapter-list-item${active?.path === item.path ? " active" : ""}`}
                onClick={() => {
                  setActivePath(item.path);
                  setEditing(false);
                }}
              >
                <strong>{item.title}</strong>
                <span>{item.path}</span>
                <em>{formatNumber(item.characters)} 字符</em>
                {item.outline_id && <small>{outlineTitleById.get(item.outline_id) ?? "已关联大纲"}</small>}
              </button>
            ))}
          </aside>

          <section className="chapter-detail">
            {active ? (
              <>
                <div className="chapter-detail-heading">
                  <div>
                    <h3>{active.title}</h3>
                    <p>
                      {active.path}
                      {active.outline_id && ` · 大纲：${outlineTitleById.get(active.outline_id) ?? active.outline_id}`}
                    </p>
                  </div>
                  <div className="chapter-detail-actions">
                    <button className="btn-secondary" onClick={() => onOpenFile(active.path)}>打开文件</button>
                    <button className="btn-secondary" onClick={() => setEditing((value) => !value)}>
                      {editing ? "预览" : "编辑"}
                    </button>
                    <button
                      className="btn-primary"
                      disabled={!changed || saving}
                      onClick={() => void onSaveDocument(active.path, draft)}
                    >
                      {saving ? "保存中" : "保存"}
                    </button>
                  </div>
                </div>
                {active.summary && (
                  <div className="chapter-summary">
                    <strong>摘要</strong>
                    <p>{active.summary}</p>
                  </div>
                )}
                {relatedForeshadows.all.length > 0 && (
                  <section className="chapter-foreshadow-panel">
                    <header>
                      <div>
                        <h4>相关伏笔</h4>
                        <p>
                          {relatedForeshadows.payoff.length} 个计划回收 · {relatedForeshadows.planting.length} 个埋设 · {relatedForeshadows.outline.length} 个大纲关联
                        </p>
                      </div>
                    </header>
                    <div className="chapter-foreshadow-groups">
                      {relatedForeshadows.payoff.length > 0 && (
                        <ForeshadowGroup title="本章计划回收" items={relatedForeshadows.payoff} />
                      )}
                      {relatedForeshadows.planting.length > 0 && (
                        <ForeshadowGroup title="本章埋设" items={relatedForeshadows.planting} />
                      )}
                      {relatedForeshadows.outline.length > 0 && (
                        <ForeshadowGroup title="同大纲节点" items={relatedForeshadows.outline} />
                      )}
                      {relatedForeshadows.related.length > 0 && (
                        <ForeshadowGroup title="相关文件" items={relatedForeshadows.related} />
                      )}
                    </div>
                  </section>
                )}
                <section className="chapter-vector-panel">
                  <header>
                    <div>
                      <h4>向量辅助</h4>
                      <p>索引{vectorStatusLabel(vectorStatus)} · {vectorStatus?.chunks ?? 0} 个片段</p>
                    </div>
                    <div className="chapter-vector-actions">
                      <button className="btn-secondary" disabled={vectorRebuilding} onClick={() => void onVectorRebuild()}>
                        {vectorRebuilding ? "重建中" : "重建索引"}
                      </button>
                      <button className="btn-secondary" disabled={vectorSearching || !active.content.trim()} onClick={() => void searchRelatedContext()}>
                        {vectorSearching ? "检索中" : "相关设定"}
                      </button>
                      <button
                        className="btn-secondary"
                        disabled={!consistencyTool}
                        onClick={() => consistencyTool && onOpenTool(consistencyTool, { path: active.path, limit: 8 })}
                      >
                        一致性检查
                      </button>
                    </div>
                  </header>
                  {vectorError && <p className="chapter-vector-error">{vectorError}</p>}
                  {showVectorResults && !vectorSearching && vectorResults.length === 0 && (
                    <p className="chapter-muted">没有检索到相关设定。</p>
                  )}
                  {showVectorResults && vectorResults.length > 0 && (
                    <div className="chapter-vector-results">
                      {vectorResults.slice(0, 5).map((item) => (
                        <article key={item.chunk_id}>
                          <div>
                            <strong>{item.path}</strong>
                            <span>{item.collection} · {item.score.toFixed(3)}</span>
                          </div>
                          <p>{item.content}</p>
                          <button className="btn-ghost" onClick={() => onOpenFile(item.path)}>打开</button>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
                <section className="chapter-meta-panel">
                  <header>
                    <h4>生产信息</h4>
                    <button
                      className="btn-primary"
                      disabled={!metadataChanged || saving}
                      onClick={() => void onSaveMetadata(active.path, {
                        ...metadataDraft,
                        summary: metadataDraft.summary.trim(),
                        target_characters: Number(metadataDraft.target_characters || 0),
                        revision: Number(metadataDraft.revision || 0),
                        outline_id: metadataDraft.outline_id,
                      })}
                    >
                      {saving ? "保存中" : "保存信息"}
                    </button>
                  </header>
                  <div className="chapter-meta-grid">
                    <label>
                      <span>状态</span>
                      <select value={metadataDraft.status} onChange={(event) => setMetadataField("status", event.target.value)}>
                        {STATUS_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>目标字数</span>
                      <input
                        type="number"
                        min={0}
                        value={metadataDraft.target_characters}
                        onChange={(event) => setMetadataField("target_characters", Number(event.target.value))}
                      />
                    </label>
                    <label>
                      <span>修订轮次</span>
                      <input
                        type="number"
                        min={0}
                        value={metadataDraft.revision}
                        onChange={(event) => setMetadataField("revision", Number(event.target.value))}
                      />
                    </label>
                    <label className="chapter-meta-wide">
                      <span>关联大纲节点</span>
                      <select
                        value={metadataDraft.outline_id}
                        onChange={(event) => setMetadataField("outline_id", event.target.value)}
                      >
                        <option value="">未关联</option>
                        {outlineItems.map((item, index) => {
                          const id = String(item.id || `outline-${index + 1}`);
                          return (
                            <option key={id} value={id}>
                              {index + 1}. {String(item.title || item.raw || `节点 ${index + 1}`)}
                            </option>
                          );
                        })}
                      </select>
                    </label>
                    <label className="chapter-meta-wide">
                      <span>摘要</span>
                      <textarea
                        rows={3}
                        value={metadataDraft.summary}
                        onChange={(event) => setMetadataField("summary", event.target.value)}
                      />
                    </label>
                  </div>
                  <div className="chapter-progress">
                    <div>
                      <span>字数进度</span>
                      <strong>{formatNumber(active.characters)} / {formatNumber(metadataDraft.target_characters || 0)}</strong>
                    </div>
                    <div className="chapter-progress-track">
                      <span style={{ width: progressWidth(active.characters, metadataDraft.target_characters || 0) }} />
                    </div>
                  </div>
                </section>
                {editing ? (
                  <textarea
                    className="chapter-editor"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    spellCheck={false}
                  />
                ) : (
                  <MarkdownView content={active.content || "暂无内容"} />
                )}
              </>
            ) : (
              <div className="chapter-empty">
                <h3>还没有章节</h3>
                <p>用写新章节工具生成第一章，或在文件视图中创建章节 Markdown。</p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
