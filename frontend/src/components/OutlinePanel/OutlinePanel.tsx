import { useEffect, useMemo, useState } from "react";
import type { OutlineItem, StoryOutline, ToolDescriptor } from "../../types";
import MarkdownView from "../MarkdownView";
import "./OutlinePanel.css";

interface OutlinePanelProps {
  outline: StoryOutline | null;
  loading: boolean;
  error: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onSave: (title: string, items: OutlineItem[]) => void | Promise<unknown>;
  onOpenTool: (tool: ToolDescriptor) => void;
}

export default function OutlinePanel({
  outline,
  loading,
  error,
  tools,
  onRefresh,
  onSave,
  onOpenTool,
}: OutlinePanelProps) {
  const outlineTool = tools.find((tool) => tool.name === "outline_generate");
  const sourceItems = useMemo(() => outline?.items ?? [], [outline?.items]);
  const [title, setTitle] = useState("大纲");
  const [draftItems, setDraftItems] = useState<OutlineItem[]>([]);
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setTitle(outline?.title || "大纲");
    setDraftItems(sourceItems.map((item, index) => ({
      index: Number(item.index ?? index + 1),
      title: String(item.title || item.raw || `节点 ${index + 1}`),
      summary: String(item.summary || ""),
    })));
    setEditing(false);
  }, [outline?.title, sourceItems]);

  const items = editing ? draftItems : sourceItems;
  const normalizedQuery = query.trim().toLowerCase();
  const visibleItems = normalizedQuery
    ? items.filter((item) => {
      const text = `${String(item.title ?? "")}\n${String(item.summary ?? "")}\n${String(item.raw ?? "")}`.toLowerCase();
      return text.includes(normalizedQuery);
    })
    : items;

  const updateItem = (index: number, patch: Partial<OutlineItem>) => {
    setDraftItems((current) => current.map((item, i) => i === index ? { ...item, ...patch } : item));
  };

  const addItem = () => {
    setEditing(true);
    setDraftItems((current) => [
      ...current,
      { index: current.length + 1, title: `节点 ${current.length + 1}`, summary: "" },
    ]);
  };

  const removeItem = (index: number) => {
    setDraftItems((current) => current.filter((_, i) => i !== index).map((item, i) => ({ ...item, index: i + 1 })));
  };

  const moveItem = (index: number, direction: -1 | 1) => {
    setDraftItems((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((item, i) => ({ ...item, index: i + 1 }));
    });
  };

  const handleSave = async () => {
    await onSave(title, draftItems.map((item, index) => ({ ...item, index: index + 1 })));
    setEditing(false);
  };

  return (
    <section className="outline-panel">
      <header className="outline-header">
        <div>
          {editing ? (
            <input
              className="outline-title-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          ) : (
            <h2>大纲管理</h2>
          )}
          <p>{outline?.source ? `${outline.source} · ${outline.format}` : "尚未建立大纲"}</p>
        </div>
        <div className="outline-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          {editing ? (
            <>
              <button className="btn-secondary" onClick={() => {
                setDraftItems(sourceItems.map((item, index) => ({
                  index: Number(item.index ?? index + 1),
                  title: String(item.title || item.raw || `节点 ${index + 1}`),
                  summary: String(item.summary || ""),
                })));
                setEditing(false);
              }}>取消</button>
              <button className="btn-primary" onClick={() => void handleSave()}>保存</button>
            </>
          ) : (
            <button className="btn-secondary" onClick={() => setEditing(true)}>编辑</button>
          )}
          <button className="btn-secondary" onClick={addItem}>新增节点</button>
          <button className="btn-primary" disabled={!outlineTool} onClick={() => outlineTool && onOpenTool(outlineTool)}>
            AI 生成/续写
          </button>
        </div>
      </header>

      {loading && <p className="outline-muted">加载大纲中…</p>}
      {error && <p className="outline-error">{error}</p>}

      {!loading && !error && (
        <section className="outline-toolbar">
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题或摘要"
          />
          <span>{visibleItems.length} / {items.length} 个节点</span>
        </section>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="outline-list">
          {visibleItems.map((item, visibleIndex) => {
            const itemIndex = items.indexOf(item);
            const index = itemIndex === -1 ? visibleIndex : itemIndex;
            return (
            <article className="outline-item" key={`${item.index ?? index}-${item.title ?? item.raw ?? index}`}>
              <div className="outline-item-index">{index + 1}</div>
              <div>
                {editing ? (
                  <div className="outline-item-edit">
                    <input
                      value={String(item.title || "")}
                      onChange={(event) => updateItem(index, { title: event.target.value })}
                    />
                    <textarea
                      rows={5}
                      value={String(item.summary || "")}
                      onChange={(event) => updateItem(index, { summary: event.target.value })}
                    />
                    <div className="outline-item-edit-actions">
                      <button className="btn-secondary" disabled={index === 0} onClick={() => moveItem(index, -1)}>上移</button>
                      <button className="btn-secondary" disabled={index === draftItems.length - 1} onClick={() => moveItem(index, 1)}>下移</button>
                      <button className="btn-danger" onClick={() => removeItem(index)}>删除</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <h3>{String(item.title || item.raw || `节点 ${index + 1}`)}</h3>
                    {item.summary && <MarkdownView content={String(item.summary)} />}
                  </>
                )}
              </div>
            </article>
          );
          })}
        </div>
      )}

      {!loading && !error && items.length > 0 && visibleItems.length === 0 && (
        <div className="outline-empty">
          <h3>没有匹配的大纲节点</h3>
          <p>换一个关键词，或清空搜索条件。</p>
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="outline-empty">
          <h3>还没有结构化大纲</h3>
          <p>可以先在 `plot/outline.md` 手写，也可以用 AI 生成/续写入口创建第一版。</p>
        </div>
      )}

      {!loading && !error && outline?.content && (
        <section className="outline-raw">
          <h3>原始 Markdown</h3>
          <MarkdownView content={outline.content} />
        </section>
      )}
    </section>
  );
}
