import { useEffect, useMemo, useState } from "react";
import type { StoryWorldview, ToolDescriptor } from "../../types";
import MarkdownView from "../MarkdownView";
import "./WorldviewPanel.css";

const WORLDVIEW_TEMPLATES = [
  {
    title: "地理",
    path: "world/geography.md",
    content: `# 地理

## 世界格局

## 主要地区

## 交通与边界

## 气候与资源

## 未定问题
`,
  },
  {
    title: "历史",
    path: "world/history.md",
    content: `# 历史

## 时代划分

## 关键事件

## 历史遗留问题

## 各势力的历史叙事

## 未定问题
`,
  },
  {
    title: "势力",
    path: "world/factions.md",
    content: `# 势力

## 势力总览

## 核心组织

## 资源与诉求

## 冲突关系

## 未定问题
`,
  },
  {
    title: "技术/魔法",
    path: "world/power-system.md",
    content: `# 技术与力量体系

## 基本原理

## 使用限制

## 代价与风险

## 代表性能力或装置

## 未定问题
`,
  },
  {
    title: "规则",
    path: "world/rules.md",
    content: `# 世界规则

## 不可违背的设定

## 可变动设定

## 禁止写法

## 需要持续检查的一致性点

## 未定问题
`,
  },
  {
    title: "年表",
    path: "world/timeline.md",
    content: `# 年表

## 远古/前史

## 近代事件

## 正文开始前

## 正文期间

## 未定问题
`,
  },
];

const WORLDVIEW_KIND_RULES = [
  { id: "overview", label: "概览", keywords: ["overview", "概述", "总览"] },
  { id: "geography", label: "地理", keywords: ["geography", "地理", "地区", "城市"] },
  { id: "history", label: "历史", keywords: ["history", "timeline", "历史", "年表"] },
  { id: "factions", label: "势力", keywords: ["faction", "势力", "组织"] },
  { id: "power", label: "技术/力量", keywords: ["power", "magic", "tech", "技术", "魔法", "力量"] },
  { id: "rules", label: "规则", keywords: ["rules", "规则", "限制"] },
];

function worldviewKind(path: string, title: string) {
  const text = `${path}\n${title}`.toLowerCase();
  return WORLDVIEW_KIND_RULES.find((rule) => rule.keywords.some((keyword) => text.includes(keyword.toLowerCase()))) ?? {
    id: "other",
    label: "其他",
  };
}

interface WorldviewPanelProps {
  worldview: StoryWorldview | null;
  loading: boolean;
  saving: boolean;
  error: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onSaveDocument: (path: string, content: string) => { path: string } | null | void | Promise<{ path: string } | null | void>;
  onRenameDocument: (oldPath: string, newPath: string) => { path: string } | null | void | Promise<{ path: string } | null | void>;
  onDeleteDocument: (path: string) => boolean | void | Promise<boolean | unknown>;
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
  onRenameDocument,
  onDeleteDocument,
  onOpenTool,
}: WorldviewPanelProps) {
  const updateTool = tools.find((tool) => tool.name === "update_worldview");
  const documents = worldview?.items ?? [];
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState("all");
  const [sortMode, setSortMode] = useState("path");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renamePath, setRenamePath] = useState("");
  const visibleDocuments = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const filtered = documents.filter((doc) => {
      if (kindFilter !== "all" && worldviewKind(doc.path, doc.title).id !== kindFilter) return false;
      if (!normalized) return true;
      return `${doc.path}\n${doc.title}\n${doc.content}`.toLowerCase().includes(normalized);
    });
    return [...filtered].sort((a, b) => {
      if (sortMode === "kind") return worldviewKind(a.path, a.title).label.localeCompare(worldviewKind(b.path, b.title).label, "zh-Hans-CN") || a.path.localeCompare(b.path, "zh-Hans-CN");
      if (sortMode === "characters_desc") return b.content.length - a.content.length || a.path.localeCompare(b.path, "zh-Hans-CN");
      if (sortMode === "characters_asc") return a.content.length - b.content.length || a.path.localeCompare(b.path, "zh-Hans-CN");
      if (sortMode === "title") return a.title.localeCompare(b.title, "zh-Hans-CN") || a.path.localeCompare(b.path, "zh-Hans-CN");
      return a.path.localeCompare(b.path, "zh-Hans-CN", { numeric: true });
    });
  }, [documents, kindFilter, query, sortMode]);
  const documentPaths = useMemo(() => new Set(documents.map((doc) => doc.path)), [documents]);
  const active = documents.find((doc) => doc.path === activePath) ?? visibleDocuments[0] ?? null;
  const kindCount = useMemo(() => {
    const map = new Map<string, number>();
    for (const doc of documents) {
      const kind = worldviewKind(doc.path, doc.title).label;
      map.set(kind, (map.get(kind) ?? 0) + 1);
    }
    return [...map.entries()];
  }, [documents]);

  useEffect(() => {
    if (!active) {
      setDraft("");
      setRenamePath("");
      return;
    }
    setDraft(active.content);
    setRenamePath(active.path);
  }, [active?.path, active?.content]);

  const changed = Boolean(active && draft !== active.content);
  const normalizedRenamePath = renamePath.trim().replace(/\\/g, "/");
  const renameInvalid = Boolean(
    active &&
    (!normalizedRenamePath.startsWith("world/") ||
      !normalizedRenamePath.endsWith(".md") ||
      normalizedRenamePath.includes("..") ||
      normalizedRenamePath === active.path)
  );

  const handleRename = async () => {
    if (!active || renameInvalid) return;
    if (!window.confirm(`确认重命名世界观文档？\n\n${active.path}\n→ ${normalizedRenamePath}\n\n影响：原文件会移动到新路径，文件树和索引随后刷新。`)) return;
    const result = await onRenameDocument(active.path, normalizedRenamePath);
    if (!result?.path) return;
    setActivePath(result.path);
    setRenaming(false);
  };

  const handleDelete = async () => {
    if (!active) return;
    if (!window.confirm(`确认删除世界观文档？\n\n${active.path}\n\n影响：该 Markdown 文件会从项目中移除，文件树和索引随后刷新。`)) return;
    const deletedPath = active.path;
    const result = await onDeleteDocument(deletedPath);
    if (result === false) return;
    setActivePath(null);
    setEditing(false);
    setRenaming(false);
  };

  const handleTemplate = async (template: typeof WORLDVIEW_TEMPLATES[number]) => {
    if (documentPaths.has(template.path)) {
      setActivePath(template.path);
      setEditing(false);
      setRenaming(false);
      return;
    }
    const result = await onSaveDocument(template.path, template.content);
    if (!result?.path) return;
    setActivePath(result.path);
    setEditing(true);
    setRenaming(false);
  };

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
        <>
        <section className="worldview-overview-strip" aria-label="世界观概览">
          <div>
            <span>文档</span>
            <strong>{documents.length}</strong>
          </div>
          <div>
            <span>分类</span>
            <strong>{kindCount.length}</strong>
          </div>
          <div>
            <span>总字符</span>
            <strong>{new Intl.NumberFormat().format(documents.reduce((total, doc) => total + doc.content.length, 0))}</strong>
          </div>
          <div>
            <span>来源</span>
            <strong>{worldview?.source ?? "world"}</strong>
          </div>
        </section>
        <div className="worldview-layout">
          <aside className="worldview-list">
            <div className="worldview-list-head">
              <div>
                <strong>设定资料库</strong>
                <span>{visibleDocuments.length} / {documents.length}</span>
              </div>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索设定"
              />
              <label className="worldview-sort-select">
                <span>排序</span>
                <select value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                  <option value="path">路径</option>
                  <option value="kind">类型</option>
                  <option value="characters_desc">字数多到少</option>
                  <option value="characters_asc">字数少到多</option>
                  <option value="title">标题</option>
                </select>
              </label>
              <div className="worldview-filter-row" aria-label="世界观类型筛选">
                <button className={kindFilter === "all" ? "active" : ""} onClick={() => setKindFilter("all")}>全部</button>
                {[...WORLDVIEW_KIND_RULES, { id: "other", label: "其他", keywords: [] }].map((kind) => (
                  <button
                    key={kind.id}
                    className={kindFilter === kind.id ? "active" : ""}
                    onClick={() => setKindFilter(kind.id)}
                  >
                    {kind.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="worldview-templates">
              <h3>主题模板</h3>
              <div className="worldview-template-grid">
                {WORLDVIEW_TEMPLATES.map((template) => {
                  const exists = documentPaths.has(template.path);
                  return (
                    <button
                      key={template.path}
                      className={`worldview-template${exists ? " exists" : ""}`}
                      disabled={saving}
                      onClick={() => void handleTemplate(template)}
                      title={template.path}
                    >
                      <strong>{template.title}</strong>
                      <span>{exists ? "打开" : "创建"}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            {visibleDocuments.length === 0 && <p className="worldview-muted">没有匹配文档</p>}
            {visibleDocuments.map((doc) => (
              <button
                key={doc.path}
                className={`worldview-list-item${active?.path === doc.path ? " active" : ""}`}
                onClick={() => {
                  setActivePath(doc.path);
                  setEditing(false);
                  setRenaming(false);
                }}
              >
                <div>
                  <strong>{doc.title}</strong>
                  <mark className={`worldview-kind is-${worldviewKind(doc.path, doc.title).id}`}>{worldviewKind(doc.path, doc.title).label}</mark>
                </div>
                <span>{doc.path}</span>
                {doc.summary && <em>{doc.summary}</em>}
              </button>
            ))}
          </aside>

          <section className="worldview-detail">
            {active ? (
              <>
                <div className="worldview-detail-heading">
                  <div>
                    <div className="worldview-title-row">
                      <h3>{active.title}</h3>
                      <mark className={`worldview-kind is-${worldviewKind(active.path, active.title).id}`}>
                        {worldviewKind(active.path, active.title).label}
                      </mark>
                    </div>
                    <p>{active.path}</p>
                    <div className="worldview-detail-metrics">
                      <span>{new Intl.NumberFormat().format(active.content.length)} 字符</span>
                      <span>{active.content.split(/\r?\n/).length} 行</span>
                    </div>
                  </div>
                  <div className="worldview-detail-actions">
                    <button className="btn-secondary" onClick={() => setRenaming((value) => !value)}>
                      {renaming ? "取消重命名" : "重命名"}
                    </button>
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
                    <button className="btn-danger" disabled={saving} onClick={() => void handleDelete()}>
                      删除
                    </button>
                  </div>
                </div>
                {renaming && (
                  <div className="worldview-rename">
                    <label>
                      新路径
                      <input
                        value={renamePath}
                        onChange={(event) => setRenamePath(event.target.value)}
                        placeholder="world/geography.md"
                      />
                    </label>
                    <button
                      className="btn-primary"
                      disabled={renameInvalid || saving}
                      onClick={() => void handleRename()}
                    >
                      {saving ? "处理中" : "确认重命名"}
                    </button>
                    {renameInvalid && <span>路径需位于 world/ 下，以 .md 结尾，且不能与原路径相同。</span>}
                  </div>
                )}
                {editing ? (
                  <textarea
                    className="worldview-editor"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    spellCheck={false}
                  />
                ) : (
                  <div className="worldview-content-surface">
                    <MarkdownView content={active.content || "暂无内容"} />
                  </div>
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
        </>
      )}
    </section>
  );
}
