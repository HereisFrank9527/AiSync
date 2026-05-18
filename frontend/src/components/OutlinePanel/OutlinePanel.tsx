import { useEffect, useMemo, useState } from "react";
import type { OutlineItem, StoryChapters, StoryOutline, ToolDescriptor } from "../../types";
import MarkdownView from "../MarkdownView";
import "./OutlinePanel.css";

interface OutlinePanelProps {
  outline: StoryOutline | null;
  chapters: StoryChapters | null;
  loading: boolean;
  error: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onSave: (title: string, items: OutlineItem[]) => void | Promise<unknown>;
  onImportMarkdown: () => void | Promise<unknown>;
  onOpenTool: (tool: ToolDescriptor) => void;
}

const STATUS_OPTIONS = [
  { value: "planned", label: "未开始" },
  { value: "draft", label: "草稿" },
  { value: "revising", label: "修订" },
  { value: "done", label: "完成" },
];

function outlineId(item: OutlineItem, index: number) {
  return String(item.id || `outline-${index + 1}`);
}

function statusLabel(status: unknown) {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label ?? "未开始";
}

export default function OutlinePanel({
  outline,
  chapters,
  loading,
  error,
  tools,
  onRefresh,
  onSave,
  onImportMarkdown,
  onOpenTool,
}: OutlinePanelProps) {
  const outlineTool = tools.find((tool) => tool.name === "outline_generate");
  const sourceItems = useMemo(() => outline?.items ?? [], [outline?.items]);
  const [title, setTitle] = useState("大纲");
  const [draftItems, setDraftItems] = useState<OutlineItem[]>([]);
  const [editing, setEditing] = useState(false);
  const [activeTab, setActiveTab] = useState<"structure" | "raw">("structure");
  const [query, setQuery] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  useEffect(() => {
    setTitle(outline?.title || "大纲");
    setDraftItems(sourceItems.map((item, index) => ({
      id: outlineId(item, index),
      index: Number(item.index ?? index + 1),
      title: String(item.title || item.raw || `节点 ${index + 1}`),
      summary: String(item.summary || ""),
      status: String(item.status || "planned"),
    })));
    setEditing(false);
  }, [outline?.title, sourceItems]);

  const items = editing ? draftItems : sourceItems;
  const markdownOnly = outline?.format === "markdown_only";
  const importableItems = outline?.importable_items ?? [];
  const linkedChapters = useMemo(() => {
    const groups = new Map<string, NonNullable<StoryChapters["items"]>>();
    for (const chapter of chapters?.items ?? []) {
      if (!chapter.outline_id) continue;
      const current = groups.get(chapter.outline_id) ?? [];
      current.push(chapter);
      groups.set(chapter.outline_id, current);
    }
    return groups;
  }, [chapters?.items]);
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
      {
        id: `outline-${Date.now().toString(36)}`,
        index: current.length + 1,
        title: `节点 ${current.length + 1}`,
        summary: "",
        status: "planned",
      },
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

  const reorderItem = (from: number, to: number) => {
    if (from === to) return;
    setDraftItems((current) => {
      if (from < 0 || from >= current.length || to < 0 || to >= current.length) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next.map((item, i) => ({ ...item, index: i + 1 }));
    });
  };

  const handleSave = async () => {
    await onSave(title, draftItems.map((item, index) => ({
      ...item,
      id: item.id || `outline-${index + 1}`,
      index: index + 1,
      status: String(item.status || "planned"),
    })));
    setEditing(false);
  };

  const resetDraft = () => {
    setDraftItems(sourceItems.map((item, index) => ({
      id: outlineId(item, index),
      index: Number(item.index ?? index + 1),
      title: String(item.title || item.raw || `节点 ${index + 1}`),
      summary: String(item.summary || ""),
      status: String(item.status || "planned"),
    })));
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
              <button className="btn-secondary" onClick={resetDraft}>取消</button>
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
        <div className="outline-tabs">
          <button className={activeTab === "structure" ? "active" : ""} onClick={() => setActiveTab("structure")}>
            结构视图
          </button>
          <button className={activeTab === "raw" ? "active" : ""} onClick={() => setActiveTab("raw")}>
            原文视图
          </button>
          <span>{markdownOnly ? "Markdown 原文尚未结构化" : `${items.length} 个结构节点`}</span>
        </div>
      )}

      {!loading && !error && activeTab === "structure" && markdownOnly && (
        <section className="outline-import-panel">
          <div>
            <h3>发现 Markdown 大纲原文</h3>
            <p>原文会完整保留在“原文视图”。结构视图只导入明确的章节标题，卷、主线、核心问题等不会被标记为未开始节点。</p>
            <span>可导入章节节点：{importableItems.length} 个</span>
          </div>
          <button className="btn-primary" disabled={importableItems.length === 0} onClick={() => void onImportMarkdown()}>
            从原文导入章节节点
          </button>
        </section>
      )}

      {!loading && !error && activeTab === "structure" && (
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

      {!loading && !error && activeTab === "structure" && items.length > 0 && (
        <div className="outline-list">
          {visibleItems.map((item, visibleIndex) => {
            const itemIndex = items.indexOf(item);
            const index = itemIndex === -1 ? visibleIndex : itemIndex;
            const id = outlineId(item, index);
            const linked = linkedChapters.get(id) ?? [];
            return (
            <article
              className={`outline-item${editing && dragIndex === index ? " dragging" : ""}`}
              key={id}
              draggable={editing}
              onDragStart={() => setDragIndex(index)}
              onDragOver={(event) => editing && event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (dragIndex === null) return;
                reorderItem(dragIndex, index);
                setDragIndex(null);
              }}
              onDragEnd={() => setDragIndex(null)}
            >
              <div className="outline-item-index">{index + 1}</div>
              <div>
                {editing ? (
                  <div className="outline-item-edit">
                    <div className="outline-item-edit-row">
                      <input
                        value={String(item.title || "")}
                        onChange={(event) => updateItem(index, { title: event.target.value })}
                      />
                      <select
                        value={String(item.status || "planned")}
                        onChange={(event) => updateItem(index, { status: event.target.value })}
                      >
                        {STATUS_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
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
                    <div className="outline-item-heading">
                      <h3>{String(item.title || item.raw || `节点 ${index + 1}`)}</h3>
                      <span className={`outline-status outline-status-${String(item.status || "planned")}`}>
                        {statusLabel(item.status)}
                      </span>
                    </div>
                    {linked.length > 0 && (
                      <div className="outline-linked-chapters">
                        {linked.map((chapter) => (
                          <span key={chapter.path}>{chapter.title} · {chapter.status || "draft"}</span>
                        ))}
                      </div>
                    )}
                    {item.summary && <MarkdownView content={String(item.summary)} />}
                  </>
                )}
              </div>
            </article>
          );
          })}
        </div>
      )}

      {!loading && !error && activeTab === "structure" && items.length > 0 && visibleItems.length === 0 && (
        <div className="outline-empty">
          <h3>没有匹配的大纲节点</h3>
          <p>换一个关键词，或清空搜索条件。</p>
        </div>
      )}

      {!loading && !error && activeTab === "structure" && items.length === 0 && !markdownOnly && (
        <div className="outline-empty">
          <h3>还没有结构化大纲</h3>
          <p>可以先在 `plot/outline.md` 手写，也可以用 AI 生成/续写入口创建第一版。</p>
        </div>
      )}

      {!loading && !error && activeTab === "raw" && outline?.content && (
        <section className="outline-raw">
          <h3>原始 Markdown</h3>
          <MarkdownView content={outline.content} />
        </section>
      )}
      {!loading && !error && activeTab === "raw" && !outline?.content && (
        <div className="outline-empty">
          <h3>暂无原文</h3>
          <p>保存结构化大纲后会同步生成可读 Markdown。</p>
        </div>
      )}
    </section>
  );
}
