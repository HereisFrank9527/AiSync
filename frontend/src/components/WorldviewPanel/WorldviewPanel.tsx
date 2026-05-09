import { useEffect, useMemo, useState } from "react";
import type { StoryWorldview, ToolDescriptor } from "../../types";
import MarkdownView from "../MarkdownView";
import "./WorldviewPanel.css";

interface WorldviewPanelProps {
  worldview: StoryWorldview | null;
  loading: boolean;
  saving: boolean;
  error: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onSaveDocument: (path: string, content: string) => void | Promise<unknown>;
  onOpenTool: (tool: ToolDescriptor) => void;
}

export default function WorldviewPanel({
  worldview,
  loading,
  saving,
  error,
  tools,
  onRefresh,
  onSaveDocument,
  onOpenTool,
}: WorldviewPanelProps) {
  const updateTool = tools.find((tool) => tool.name === "update_worldview");
  const documents = worldview?.items ?? [];
  const [query, setQuery] = useState("");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const visibleDocuments = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return documents;
    return documents.filter((doc) => `${doc.path}\n${doc.title}\n${doc.content}`.toLowerCase().includes(normalized));
  }, [documents, query]);
  const active = documents.find((doc) => doc.path === activePath) ?? visibleDocuments[0] ?? null;

  useEffect(() => {
    if (!active) {
      setDraft("");
      return;
    }
    setDraft(active.content);
  }, [active?.path, active?.content]);

  const changed = Boolean(active && draft !== active.content);

  return (
    <section className="worldview-panel">
      <header className="worldview-header">
        <div>
          <h2>世界观整理</h2>
          <p>{worldview?.source ?? "world"} · {documents.length} 份文档</p>
        </div>
        <div className="worldview-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-primary" disabled={!updateTool} onClick={() => updateTool && onOpenTool(updateTool)}>
            更新世界观
          </button>
        </div>
      </header>

      {loading && <p className="worldview-muted">加载世界观中…</p>}
      {error && <p className="worldview-error">{error}</p>}

      {!loading && !error && (
        <div className="worldview-layout">
          <aside className="worldview-list">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索设定"
            />
            {visibleDocuments.length === 0 && <p className="worldview-muted">没有匹配文档</p>}
            {visibleDocuments.map((doc) => (
              <button
                key={doc.path}
                className={`worldview-list-item${active?.path === doc.path ? " active" : ""}`}
                onClick={() => {
                  setActivePath(doc.path);
                  setEditing(false);
                }}
              >
                <strong>{doc.title}</strong>
                <span>{doc.path}</span>
              </button>
            ))}
          </aside>

          <section className="worldview-detail">
            {active ? (
              <>
                <div className="worldview-detail-heading">
                  <div>
                    <h3>{active.title}</h3>
                    <p>{active.path}</p>
                  </div>
                  <div className="worldview-detail-actions">
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
                {editing ? (
                  <textarea
                    className="worldview-editor"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    spellCheck={false}
                  />
                ) : (
                  <MarkdownView content={active.content || "暂无内容"} />
                )}
              </>
            ) : (
              <div className="worldview-empty">
                <h3>还没有世界观文档</h3>
                <p>用更新世界观工具创建第一份设定文档。</p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
