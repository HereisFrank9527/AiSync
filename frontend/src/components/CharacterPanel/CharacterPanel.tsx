import { useEffect, useMemo, useState } from "react";
import type {
  ArchivedStoryCharacter,
  StoryCharacter,
  StoryCharacters,
  StoryCharacterUpdate,
  ToolDescriptor,
} from "../../types";
import MarkdownView from "../MarkdownView";
import "./CharacterPanel.css";

const STATUS_LABELS: Record<string, string> = {
  active: "活跃",
  inactive: "暂离",
  missing: "失踪",
  deceased: "死亡",
  retired: "退场",
  unknown: "未定",
};

const STATUS_OPTIONS = Object.entries(STATUS_LABELS);

function characterDraft(character: StoryCharacter): StoryCharacterUpdate {
  return {
    slug: character.slug,
    name: character.name,
    role: character.role,
    summary: character.summary,
    aliases: [...character.aliases],
    status: character.status,
    faction: character.faction,
    tags: [...character.tags],
    first_appearance: character.first_appearance,
    profile: character.profile,
  };
}

function splitList(value: string) {
  return Array.from(new Set(value.split(/[,，、\n]/).map((item) => item.trim()).filter(Boolean)));
}

function characterInitial(name: string) {
  return name.trim().slice(0, 1) || "?";
}

function formatArchiveTime(value: string) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

interface CharacterPanelProps {
  characters: StoryCharacters | null;
  loading: boolean;
  saving: boolean;
  error: string;
  tools: ToolDescriptor[];
  onRefresh: () => void;
  onOpenTool: (tool: ToolDescriptor) => void;
  onSaveCharacter: (character: StoryCharacterUpdate) => StoryCharacter | null | void | Promise<StoryCharacter | null | void>;
  onArchiveCharacter: (slug: string, reason?: string) => void | Promise<unknown>;
  onRestoreCharacter: (archiveId: string) => void | Promise<unknown>;
  focusedCharacterId?: string | null;
}

export default function CharacterPanel({
  characters,
  loading,
  saving,
  error,
  tools,
  onRefresh,
  onOpenTool,
  onSaveCharacter,
  onArchiveCharacter,
  onRestoreCharacter,
  focusedCharacterId,
}: CharacterPanelProps) {
  const createTool = tools.find((tool) => tool.name === "create_character");
  const items = characters?.items ?? [];
  const archives = characters?.archives ?? [];
  const warnings = characters?.warnings ?? [];
  const lastMigration = characters?.migration?.last_run;
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [draft, setDraft] = useState<StoryCharacterUpdate | null>(null);
  const [editing, setEditing] = useState(false);
  const [showArchives, setShowArchives] = useState(false);
  const [archiveReason, setArchiveReason] = useState("");
  const [confirmingArchive, setConfirmingArchive] = useState(false);
  const [actionError, setActionError] = useState("");

  const roles = useMemo(
    () => Array.from(new Set(items.map((item) => item.role.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, "zh-Hans-CN")),
    [items],
  );
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return items.filter((item) => {
      if (roleFilter !== "all" && item.role !== roleFilter) return false;
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (!normalized) return true;
      return [item.name, item.role, item.summary, item.slug, item.faction, item.aliases.join(" "), item.tags.join(" ")]
        .join("\n")
        .toLowerCase()
        .includes(normalized);
    });
  }, [items, query, roleFilter, statusFilter]);
  const active = items.find((item) => item.slug === activeSlug) ?? visibleItems[0] ?? null;
  const activeCount = items.filter((item) => item.status === "active").length;
  const factionCount = new Set(items.map((item) => item.faction.trim()).filter(Boolean)).size;

  useEffect(() => {
    if (!active) {
      setDraft(null);
      setEditing(false);
      return;
    }
    setDraft(characterDraft(active));
    setActionError("");
  }, [active?.slug, active?.name, active?.role, active?.summary, active?.profile, active?.status, active?.faction, active?.first_appearance, active?.aliases, active?.tags]);

  useEffect(() => {
    if (!focusedCharacterId) return;
    const target = items.find((item) => item.character_id === focusedCharacterId);
    if (target) {
      setActiveSlug(target.slug);
      setShowArchives(false);
      return;
    }
    if (archives.some((item) => item.character_id === focusedCharacterId)) {
      setShowArchives(true);
    }
  }, [archives, focusedCharacterId, items]);

  const changed = Boolean(active && draft && JSON.stringify(draft) !== JSON.stringify(characterDraft(active)));

  const selectCharacter = (slug: string) => {
    if (changed && !window.confirm("当前人物资料尚未保存，确认放弃修改并切换角色？")) return;
    setActiveSlug(slug);
    setEditing(false);
    setConfirmingArchive(false);
    setArchiveReason("");
  };

  const saveActive = async () => {
    if (!draft || !draft.name.trim()) return;
    try {
      const saved = await onSaveCharacter(draft);
      if (saved?.slug) setActiveSlug(saved.slug);
      setEditing(false);
      setActionError("");
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "角色保存失败");
    }
  };

  const archiveActive = async () => {
    if (!active) return;
    try {
      await onArchiveCharacter(active.slug, archiveReason.trim());
      setActiveSlug(null);
      setConfirmingArchive(false);
      setArchiveReason("");
      setEditing(false);
      setActionError("");
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "角色归档失败");
    }
  };

  const restoreArchive = async (archive: ArchivedStoryCharacter) => {
    if (!window.confirm(`恢复角色“${archive.name}”？\n\n角色文件将移回 characters/${archive.slug}/。`)) return;
    try {
      await onRestoreCharacter(archive.archive_id);
      setActiveSlug(archive.slug);
      setShowArchives(false);
      setActionError("");
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "角色恢复失败");
    }
  };

  const resetDraft = () => {
    if (active) setDraft(characterDraft(active));
    setEditing(false);
    setActionError("");
  };

  return (
    <section className="character-panel">
      <header className="character-header">
        <div>
          <h2>人物档案</h2>
          <p>{characters?.source ?? "characters"} · 管理角色资料、状态与归档</p>
        </div>
        <div className="character-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-secondary" onClick={() => setShowArchives((value) => !value)}>
            归档 {archives.length > 0 ? `(${archives.length})` : ""}
          </button>
          <button className="btn-primary" disabled={!createTool} onClick={() => createTool && onOpenTool(createTool)}>
            创建角色
          </button>
        </div>
      </header>

      {loading && <p className="character-muted">加载角色中…</p>}
      {error && <p className="character-error">{error}</p>}
      {actionError && <p className="character-error">{actionError}</p>}
      {warnings.length > 0 && (
        <details className="character-warning">
          <summary>{warnings.length} 份角色文件未能完整读取</summary>
          {warnings.map((warning) => <p key={`${warning.path}-${warning.message}`}>{warning.path}：{warning.message}</p>)}
        </details>
      )}
      {lastMigration && lastMigration.changed > 0 && (
        <details className="character-warning">
          <summary>旧人物数据已升级：{lastMigration.changed} 份档案获得永久角色 ID</summary>
          <p>其中新建元数据 {lastMigration.created_metadata} 份；人物 Markdown 与章节正文没有修改。</p>
          {lastMigration.snapshot_path && <p>迁移前快照：{lastMigration.snapshot_path}</p>}
        </details>
      )}

      {!loading && (
        <>
          <section className="character-overview-strip" aria-label="人物概览">
            <div><span>角色</span><strong>{items.length}</strong></div>
            <div><span>活跃</span><strong>{activeCount}</strong></div>
            <div><span>阵营</span><strong>{factionCount}</strong></div>
            <div><span>已归档</span><strong>{archives.length}</strong></div>
          </section>

          <div className="character-layout">
            <aside className="character-list">
              <div className="character-list-head">
                <div><strong>角色目录</strong><span>{visibleItems.length} / {items.length}</span></div>
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索姓名、别名、阵营或标签" />
                <div className="character-filter-row">
                  <label>
                    <span>定位</span>
                    <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                      <option value="all">全部定位</option>
                      {roles.map((role) => <option value={role} key={role}>{role}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>状态</span>
                    <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                      <option value="all">全部状态</option>
                      {STATUS_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                    </select>
                  </label>
                </div>
              </div>

              <div className="character-list-scroll">
                {visibleItems.length === 0 && <p className="character-muted">没有匹配角色</p>}
                {visibleItems.map((item) => (
                  <button
                    key={item.slug}
                    className={`character-list-item${active?.slug === item.slug ? " active" : ""}`}
                    onClick={() => selectCharacter(item.slug)}
                  >
                    <span className="character-list-avatar">{characterInitial(item.name)}</span>
                    <span className="character-list-copy">
                      <span><strong>{item.name}</strong><mark className={`character-status is-${item.status}`}>{STATUS_LABELS[item.status] ?? "未定"}</mark></span>
                      <em>{item.role || "未设置定位"}{item.faction ? ` · ${item.faction}` : ""}</em>
                      {(item.aliases.length > 0 || item.tags.length > 0) && <small>{[...item.aliases, ...item.tags].slice(0, 3).join(" / ")}</small>}
                    </span>
                  </button>
                ))}
              </div>

              {showArchives && (
                <section className="character-archive-list">
                  <div><strong>可恢复归档</strong><span>{archives.length}</span></div>
                  {archives.length === 0 && <p className="character-muted">暂无归档角色</p>}
                  {archives.map((archive) => (
                    <div className="character-archive-item" key={archive.archive_id}>
                      <div>
                        <strong>{archive.name}</strong>
                        <span>{archive.role || archive.slug}</span>
                        <small>{archive.reason || formatArchiveTime(archive.archived_at)}</small>
                      </div>
                      <button className="btn-ghost" disabled={saving} onClick={() => void restoreArchive(archive)}>恢复</button>
                    </div>
                  ))}
                </section>
              )}
            </aside>

            <section className="character-detail">
              {active && draft ? (
                <>
                  <div className="character-detail-heading">
                    <div className="character-identity">
                      <span className="character-avatar">{characterInitial(active.name)}</span>
                      <div>
                        <div className="character-title-row">
                          <h3>{active.name}</h3>
                          <mark className={`character-status is-${active.status}`}>{STATUS_LABELS[active.status] ?? "未定"}</mark>
                        </div>
                        <p>{active.role || "未设置叙事定位"}{active.faction ? ` · ${active.faction}` : ""}</p>
                        <small>{active.slug} · {active.character_id} · schema v{active.schema_version}</small>
                      </div>
                    </div>
                    <div className="character-detail-actions">
                      {editing ? (
                        <>
                          <button className="btn-secondary" disabled={saving} onClick={resetDraft}>取消</button>
                          <button className="btn-primary" disabled={!changed || saving || !draft.name.trim()} onClick={() => void saveActive()}>
                            {saving ? "保存中" : "保存资料"}
                          </button>
                        </>
                      ) : (
                        <>
                          <button className="btn-secondary" onClick={() => setEditing(true)}>编辑资料</button>
                          <button className="btn-danger" onClick={() => setConfirmingArchive(true)}>归档</button>
                        </>
                      )}
                    </div>
                  </div>

                  {confirmingArchive && !editing && (
                    <div className="character-archive-confirm">
                      <div>
                        <strong>归档 {active.name}</strong>
                        <p>角色文件将移入临时归档区，可以从左侧归档列表恢复。</p>
                      </div>
                      <input value={archiveReason} onChange={(event) => setArchiveReason(event.target.value)} placeholder="归档原因，例如旧名、重复角色或废弃设定" />
                      <div>
                        <button className="btn-secondary" onClick={() => setConfirmingArchive(false)}>取消</button>
                        <button className="btn-danger" disabled={saving} onClick={() => void archiveActive()}>{saving ? "处理中" : "确认归档"}</button>
                      </div>
                    </div>
                  )}

                  {editing ? (
                    <div className="character-editor">
                      <section className="character-editor-section">
                        <div className="character-section-heading"><h4>基础资料</h4><span>保存到 profile.yaml</span></div>
                        <div className="character-form-grid">
                          <label><span>姓名</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
                          <label><span>叙事定位</span><input value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value })} placeholder="主角、盟友、反派…" /></label>
                          <label>
                            <span>当前状态</span>
                            <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
                              {STATUS_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                            </select>
                          </label>
                          <label><span>阵营 / 组织</span><input value={draft.faction} onChange={(event) => setDraft({ ...draft, faction: event.target.value })} /></label>
                          <label><span>首次出场</span><input value={draft.first_appearance} onChange={(event) => setDraft({ ...draft, first_appearance: event.target.value })} placeholder="第一章或 outline 节点" /></label>
                          <label><span>角色标识</span><input value={draft.slug} disabled title="角色标识暂不在此修改，避免断开已有文件引用。" /></label>
                          <label className="character-form-wide"><span>别名 / 旧名 / 称号</span><input value={draft.aliases.join("、")} onChange={(event) => setDraft({ ...draft, aliases: splitList(event.target.value) })} placeholder="用逗号或顿号分隔" /></label>
                          <label className="character-form-wide"><span>标签</span><input value={draft.tags.join("、")} onChange={(event) => setDraft({ ...draft, tags: splitList(event.target.value) })} placeholder="能力、身份、性格关键词" /></label>
                          <label className="character-form-wide"><span>一句话简介</span><textarea rows={3} value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} /></label>
                        </div>
                      </section>
                      <section className="character-editor-section">
                        <div className="character-section-heading"><h4>自由档案</h4><span>保存到 profile.md</span></div>
                        <textarea className="character-profile-editor" value={draft.profile} onChange={(event) => setDraft({ ...draft, profile: event.target.value })} />
                      </section>
                    </div>
                  ) : (
                    <div className="character-profile-view">
                      <section className="character-facts" aria-label="角色基础资料">
                        <div><span>定位</span><strong>{active.role || "未设置"}</strong></div>
                        <div><span>阵营</span><strong>{active.faction || "未设置"}</strong></div>
                        <div><span>首次出场</span><strong>{active.first_appearance || "未设置"}</strong></div>
                        <div><span>档案长度</span><strong>{new Intl.NumberFormat().format(active.profile.length)} 字符</strong></div>
                      </section>

                      {active.summary && <p className="character-summary">{active.summary}</p>}
                      {(active.aliases.length > 0 || active.tags.length > 0) && (
                        <div className="character-chip-groups">
                          {active.aliases.length > 0 && <div><span>别名</span><p>{active.aliases.map((item) => <mark key={item}>{item}</mark>)}</p></div>}
                          {active.tags.length > 0 && <div><span>标签</span><p>{active.tags.map((item) => <mark key={item}>{item}</mark>)}</p></div>}
                        </div>
                      )}
                      <div className="character-profile-heading"><h4>人物档案</h4><span>{active.profile_path}</span></div>
                      <div className="character-profile-markdown">
                        {active.profile ? <MarkdownView content={active.profile} /> : <p className="character-muted">暂无角色档案正文</p>}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="character-empty">
                  <h3>还没有角色</h3>
                  <p>创建第一份人物档案后，可在这里维护基础资料与自由设定。</p>
                  <button className="btn-primary" disabled={!createTool} onClick={() => createTool && onOpenTool(createTool)}>创建角色</button>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </section>
  );
}
