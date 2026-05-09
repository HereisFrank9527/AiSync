import { useMemo, useState } from "react";
import type { StoryCharacters, ToolDescriptor } from "../../types";
import MarkdownView from "../MarkdownView";
import "./CharacterPanel.css";

interface CharacterPanelProps {
  characters: StoryCharacters | null;
  loading: boolean;
  error: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onOpenTool: (tool: ToolDescriptor) => void;
}

export default function CharacterPanel({
  characters,
  loading,
  error,
  tools,
  onRefresh,
  onOpenTool,
}: CharacterPanelProps) {
  const createTool = tools.find((tool) => tool.name === "create_character");
  const items = characters?.items ?? [];
  const [query, setQuery] = useState("");
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return items;
    return items.filter((item) => `${item.name}\n${item.role}\n${item.summary}\n${item.slug}`.toLowerCase().includes(normalized));
  }, [items, query]);
  const active = items.find((item) => item.slug === activeSlug) ?? visibleItems[0] ?? null;

  return (
    <section className="character-panel">
      <header className="character-header">
        <div>
          <h2>角色管理</h2>
          <p>{characters?.source ?? "characters"} · {items.length} 个角色</p>
        </div>
        <div className="character-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-primary" disabled={!createTool} onClick={() => createTool && onOpenTool(createTool)}>
            创建角色
          </button>
        </div>
      </header>

      {loading && <p className="character-muted">加载角色中…</p>}
      {error && <p className="character-error">{error}</p>}

      {!loading && !error && (
        <div className="character-layout">
          <aside className="character-list">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索角色"
            />
            {visibleItems.length === 0 && <p className="character-muted">没有匹配角色</p>}
            {visibleItems.map((item) => (
              <button
                key={item.slug}
                className={`character-list-item${active?.slug === item.slug ? " active" : ""}`}
                onClick={() => setActiveSlug(item.slug)}
              >
                <strong>{item.name}</strong>
                <span>{item.role || item.slug}</span>
              </button>
            ))}
          </aside>

          <section className="character-detail">
            {active ? (
              <>
                <div className="character-detail-heading">
                  <div>
                    <h3>{active.name}</h3>
                    <p>{active.role || active.slug}</p>
                  </div>
                  <small>{active.metadata_path}</small>
                </div>
                {active.summary && (
                  <div className="character-summary">
                    <strong>简介</strong>
                    <p>{active.summary}</p>
                  </div>
                )}
                {active.profile ? <MarkdownView content={active.profile} /> : <p className="character-muted">暂无角色档案正文</p>}
              </>
            ) : (
              <div className="character-empty">
                <h3>还没有角色</h3>
                <p>用创建角色工具生成第一份角色档案。</p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
