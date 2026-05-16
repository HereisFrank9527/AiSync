import { useEffect, useMemo, useState } from "react";
import type { ForeshadowItem, StoryChapters, StoryForeshadows, StoryOutline } from "../../types";
import "./ForeshadowPanel.css";

interface ForeshadowPanelProps {
  foreshadows: StoryForeshadows | null;
  outline: StoryOutline | null;
  chapters: StoryChapters | null;
  loading: boolean;
  saving: boolean;
  error: string;
  onRefresh: () => void;
  onSave: (items: ForeshadowItem[]) => void | Promise<unknown>;
}

const STATUS_OPTIONS = [
  { value: "planned", label: "计划埋" },
  { value: "planted", label: "已埋下" },
  { value: "developing", label: "推进中" },
  { value: "paid_off", label: "已回收" },
  { value: "abandoned", label: "废弃" },
];

const IMPORTANCE_OPTIONS = [
  { value: "minor", label: "轻量" },
  { value: "medium", label: "普通" },
  { value: "major", label: "关键" },
];

function itemId(index: number) {
  return `foreshadow-${Date.now().toString(36)}-${index}`;
}

function emptyItem(index: number): ForeshadowItem {
  return {
    id: itemId(index),
    title: `伏笔 ${index}`,
    summary: "",
    status: "planned",
    importance: "medium",
    plant_chapter: "",
    payoff_chapter: "",
    outline_ids: [],
    related_files: [],
    tags: [],
    notes: "",
  };
}

function statusLabel(value: string) {
  return STATUS_OPTIONS.find((option) => option.value === value)?.label ?? "计划埋";
}

function importanceLabel(value: string) {
  return IMPORTANCE_OPTIONS.find((option) => option.value === value)?.label ?? "普通";
}

function splitLines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function joinLines(values: string[]) {
  return values.join("\n");
}

export default function ForeshadowPanel({
  foreshadows,
  outline,
  chapters,
  loading,
  saving,
  error,
  onRefresh,
  onSave,
}: ForeshadowPanelProps) {
  const sourceItems = useMemo(() => foreshadows?.items ?? [], [foreshadows?.items]);
  const [draftItems, setDraftItems] = useState<ForeshadowItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [importanceFilter, setImportanceFilter] = useState("");

  useEffect(() => {
    setDraftItems(sourceItems.map((item, index) => ({ ...emptyItem(index + 1), ...item })));
  }, [sourceItems]);

  const active = draftItems.find((item) => item.id === activeId) ?? draftItems[0] ?? null;
  const chaptersList = chapters?.items ?? [];
  const outlineItems = outline?.items ?? [];
  const outlineTitleById = useMemo(() => {
    const titles = new Map<string, string>();
    outlineItems.forEach((item, index) => {
      const id = String(item.id || `outline-${index + 1}`);
      titles.set(id, String(item.title || item.raw || `节点 ${index + 1}`));
    });
    return titles;
  }, [outlineItems]);
  const chapterTitleByPath = useMemo(() => {
    const titles = new Map<string, string>();
    chaptersList.forEach((chapter) => titles.set(chapter.path, chapter.title));
    return titles;
  }, [chaptersList]);
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return draftItems.filter((item) => {
      if (statusFilter && item.status !== statusFilter) return false;
      if (importanceFilter && item.importance !== importanceFilter) return false;
      if (!normalized) return true;
      return [
        item.title,
        item.summary,
        item.notes,
        item.tags.join(" "),
        item.related_files.join(" "),
        item.plant_chapter,
        item.payoff_chapter,
      ].join("\n").toLowerCase().includes(normalized);
    });
  }, [draftItems, importanceFilter, query, statusFilter]);

  const changed = JSON.stringify(sourceItems) !== JSON.stringify(draftItems);
  const paidOffCount = draftItems.filter((item) => item.status === "paid_off").length;
  const openCount = draftItems.length - paidOffCount;

  const updateActive = (patch: Partial<ForeshadowItem>) => {
    if (!active) return;
    setDraftItems((current) => current.map((item) => item.id === active.id ? { ...item, ...patch } : item));
  };

  const addItem = () => {
    const next = emptyItem(draftItems.length + 1);
    setDraftItems((current) => [next, ...current]);
    setActiveId(next.id);
  };

  const removeActive = () => {
    if (!active) return;
    if (!window.confirm(`确定删除伏笔「${active.title}」？`)) return;
    setDraftItems((current) => current.filter((item) => item.id !== active.id));
    setActiveId(null);
  };

  const toggleOutline = (id: string) => {
    if (!active) return;
    const next = active.outline_ids.includes(id)
      ? active.outline_ids.filter((item) => item !== id)
      : [...active.outline_ids, id];
    updateActive({ outline_ids: next });
  };

  return (
    <section className="foreshadow-panel">
      <header className="foreshadow-header">
        <div>
          <h2>伏笔管理</h2>
          <p>{foreshadows?.source ?? "plot/foreshadows.json"} · {draftItems.length} 条伏笔</p>
        </div>
        <div className="foreshadow-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-secondary" onClick={addItem}>新增伏笔</button>
          <button className="btn-primary" disabled={!changed || saving} onClick={() => void onSave(draftItems)}>
            {saving ? "保存中" : "保存"}
          </button>
        </div>
      </header>

      {loading && <p className="foreshadow-muted">加载伏笔中…</p>}
      {error && <p className="foreshadow-error">{error}</p>}

      {!loading && !error && (
        <div className="foreshadow-layout">
          <aside className="foreshadow-list">
            <div className="foreshadow-stats">
              <div><span>未回收</span><strong>{openCount}</strong></div>
              <div><span>已回收</span><strong>{paidOffCount}</strong></div>
            </div>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索伏笔" />
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">全部状态</option>
              {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <select value={importanceFilter} onChange={(event) => setImportanceFilter(event.target.value)}>
              <option value="">全部重要性</option>
              {IMPORTANCE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            {visibleItems.length === 0 && <p className="foreshadow-muted">没有匹配伏笔</p>}
            {visibleItems.map((item) => (
              <button
                key={item.id}
                className={`foreshadow-list-item${active?.id === item.id ? " active" : ""}`}
                onClick={() => setActiveId(item.id)}
              >
                <strong>{item.title}</strong>
                <span>{statusLabel(item.status)} · {importanceLabel(item.importance)}</span>
                {item.tags.length > 0 && <em>{item.tags.join(" / ")}</em>}
              </button>
            ))}
          </aside>

          <section className="foreshadow-detail">
            {active ? (
              <>
                <div className="foreshadow-detail-heading">
                  <div>
                    <h3>{active.title}</h3>
                    <p>{statusLabel(active.status)} · {importanceLabel(active.importance)}</p>
                  </div>
                  <button className="btn-danger" onClick={removeActive}>删除</button>
                </div>
                <div className="foreshadow-form-grid">
                  <label>
                    <span>标题</span>
                    <input value={active.title} onChange={(event) => updateActive({ title: event.target.value })} />
                  </label>
                  <label>
                    <span>状态</span>
                    <select value={active.status} onChange={(event) => updateActive({ status: event.target.value })}>
                      {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>重要性</span>
                    <select value={active.importance} onChange={(event) => updateActive({ importance: event.target.value })}>
                      {IMPORTANCE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>埋设章节</span>
                    <select value={active.plant_chapter} onChange={(event) => updateActive({ plant_chapter: event.target.value })}>
                      <option value="">未指定</option>
                      {chaptersList.map((chapter) => <option key={chapter.path} value={chapter.path}>{chapter.title}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>回收章节</span>
                    <select value={active.payoff_chapter} onChange={(event) => updateActive({ payoff_chapter: event.target.value })}>
                      <option value="">未指定</option>
                      {chaptersList.map((chapter) => <option key={chapter.path} value={chapter.path}>{chapter.title}</option>)}
                    </select>
                  </label>
                  <label className="foreshadow-form-wide">
                    <span>摘要</span>
                    <textarea rows={3} value={active.summary} onChange={(event) => updateActive({ summary: event.target.value })} />
                  </label>
                  <label className="foreshadow-form-wide">
                    <span>标签（逗号分隔）</span>
                    <input
                      value={active.tags.join(", ")}
                      onChange={(event) => updateActive({ tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })}
                    />
                  </label>
                  <label className="foreshadow-form-wide">
                    <span>相关文件（每行一个路径）</span>
                    <textarea rows={3} value={joinLines(active.related_files)} onChange={(event) => updateActive({ related_files: splitLines(event.target.value) })} />
                  </label>
                  <div className="foreshadow-form-wide">
                    <span className="foreshadow-label">关联大纲节点</span>
                    <div className="foreshadow-outline-options">
                      {outlineItems.length === 0 && <p className="foreshadow-muted">还没有可关联的大纲节点。</p>}
                      {outlineItems.map((item, index) => {
                        const id = String(item.id || `outline-${index + 1}`);
                        return (
                          <label key={id}>
                            <input type="checkbox" checked={active.outline_ids.includes(id)} onChange={() => toggleOutline(id)} />
                            <span>{outlineTitleById.get(id)}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <label className="foreshadow-form-wide">
                    <span>备注</span>
                    <textarea rows={5} value={active.notes} onChange={(event) => updateActive({ notes: event.target.value })} />
                  </label>
                </div>
                {(active.plant_chapter || active.payoff_chapter) && (
                  <div className="foreshadow-links">
                    {active.plant_chapter && <span>埋设：{chapterTitleByPath.get(active.plant_chapter) ?? active.plant_chapter}</span>}
                    {active.payoff_chapter && <span>回收：{chapterTitleByPath.get(active.payoff_chapter) ?? active.payoff_chapter}</span>}
                  </div>
                )}
              </>
            ) : (
              <div className="foreshadow-empty">
                <h3>还没有伏笔</h3>
                <p>新增一条伏笔，记录它在哪里埋下、计划在哪里回收。</p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
