import { useEffect, useMemo, useState } from "react";
import type {
  StoryChapter,
  StoryChapterMetadataUpdate,
  StoryChapters,
  ToolDescriptor,
  VectorIndexStatus,
  VectorSearchResult,
} from "../../types";
import MarkdownView from "../MarkdownView";
import "./ChapterPanel.css";

interface ChapterPanelProps {
  chapters: StoryChapters | null;
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

export default function ChapterPanel({
  chapters,
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
  const [query, setQuery] = useState("");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [metadataDraft, setMetadataDraft] = useState<StoryChapterMetadataUpdate>({
    status: "draft",
    summary: "",
    target_characters: 0,
    revision: 0,
  });
  const [editing, setEditing] = useState(false);
  const [showVectorResults, setShowVectorResults] = useState(false);
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return items;
    return items.filter((item) => `${item.path}\n${item.title}\n${item.summary}\n${item.content}`.toLowerCase().includes(normalized));
  }, [items, query]);
  const active = items.find((item) => item.path === activePath) ?? visibleItems[0] ?? null;

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
    });
    setShowVectorResults(false);
  }, [active]);

  const changed = Boolean(active && draft !== active.content);
  const metadataChanged = Boolean(active && (
    metadataDraft.status !== active.status ||
    metadataDraft.summary !== active.summary ||
    Number(metadataDraft.target_characters || 0) !== active.target_characters ||
    Number(metadataDraft.revision || 0) !== active.revision
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
              </button>
            ))}
          </aside>

          <section className="chapter-detail">
            {active ? (
              <>
                <div className="chapter-detail-heading">
                  <div>
                    <h3>{active.title}</h3>
                    <p>{active.path}</p>
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
