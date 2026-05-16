import { useEffect, useState } from "react";
import type { ProjectOverview, ProjectOverviewUpdate } from "../../types";
import "./OverviewPanel.css";

interface OverviewPanelProps {
  overview: ProjectOverview | null;
  loading: boolean;
  saving: boolean;
  error: string;
  onRefresh: () => void;
  onSave: (data: ProjectOverviewUpdate) => void | Promise<unknown>;
  onOpenFile: (path: string) => void;
}

const STATUS_OPTIONS = [
  { value: "planning", label: "规划中" },
  { value: "drafting", label: "写作中" },
  { value: "revising", label: "修订中" },
  { value: "paused", label: "暂停" },
  { value: "completed", label: "已完成" },
];

function formatNumber(value: number) {
  return new Intl.NumberFormat().format(value);
}

function percent(value: number) {
  return `${Math.round((value || 0) * 100)}%`;
}

export default function OverviewPanel({
  overview,
  loading,
  saving,
  error,
  onRefresh,
  onSave,
  onOpenFile,
}: OverviewPanelProps) {
  const [draft, setDraft] = useState<ProjectOverviewUpdate>({
    name: "",
    status: "planning",
    synopsis: "",
    goal: "",
    target_chapters: 0,
    target_characters: 0,
  });

  useEffect(() => {
    if (!overview) return;
    setDraft({
      name: overview.name,
      status: overview.status || "planning",
      synopsis: overview.synopsis || "",
      goal: overview.goal || "",
      target_chapters: overview.target_chapters || 0,
      target_characters: overview.target_characters || 0,
    });
  }, [overview]);

  const stats = overview?.stats;
  const changed = Boolean(overview && (
    draft.name.trim() !== overview.name ||
    draft.status !== overview.status ||
    draft.synopsis.trim() !== overview.synopsis ||
    draft.goal.trim() !== overview.goal ||
    Number(draft.target_chapters || 0) !== overview.target_chapters ||
    Number(draft.target_characters || 0) !== overview.target_characters
  ));
  const canSave = Boolean(draft.name.trim()) && changed && !saving;
  const setField = <K extends keyof ProjectOverviewUpdate>(key: K, value: ProjectOverviewUpdate[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  return (
    <section className="overview-panel">
      <header className="overview-header">
        <div>
          <h2>基础信息</h2>
          <p>{overview?.path ?? "未选择项目"}</p>
        </div>
        <button className="btn-secondary" onClick={onRefresh}>刷新</button>
      </header>

      {loading && <p className="overview-muted">加载基础信息中…</p>}
      {error && <p className="overview-error">{error}</p>}

      {!loading && !error && overview && (
        <div className="overview-content">
          <section className="overview-project-panel">
            <header>
              <h3>项目信息</h3>
              <button
                className="btn-primary"
                disabled={!canSave}
                onClick={() => void onSave({
                  ...draft,
                  name: draft.name.trim(),
                  synopsis: draft.synopsis.trim(),
                  goal: draft.goal.trim(),
                  target_chapters: Number(draft.target_chapters || 0),
                  target_characters: Number(draft.target_characters || 0),
                })}
              >
                {saving ? "保存中" : "保存"}
              </button>
            </header>
            <div className="overview-form-grid">
              <label>
                <span>小说名</span>
                <input
                  value={draft.name}
                  onChange={(event) => setField("name", event.target.value)}
                  placeholder="输入小说名"
                />
              </label>
              <label>
                <span>当前状态</span>
                <select value={draft.status} onChange={(event) => setField("status", event.target.value)}>
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>计划章节数</span>
                <input
                  type="number"
                  min={0}
                  value={draft.target_chapters}
                  onChange={(event) => setField("target_chapters", Number(event.target.value))}
                />
              </label>
              <label>
                <span>目标字数</span>
                <input
                  type="number"
                  min={0}
                  value={draft.target_characters}
                  onChange={(event) => setField("target_characters", Number(event.target.value))}
                />
              </label>
              <label className="overview-form-wide">
                <span>创作目标</span>
                <input
                  value={draft.goal}
                  onChange={(event) => setField("goal", event.target.value)}
                  placeholder="例如：完成第一卷草稿"
                />
              </label>
              <label className="overview-form-wide">
                <span>简介</span>
                <textarea
                  rows={4}
                  value={draft.synopsis}
                  onChange={(event) => setField("synopsis", event.target.value)}
                  placeholder="写下作品核心设定、主线或当前创作方向"
                />
              </label>
            </div>
          </section>

          {stats && (
            <section className="overview-stats">
              <div>
                <span>已完成章节</span>
                <strong>{formatNumber(stats.completed_chapters)}</strong>
              </div>
              <div>
                <span>正文字符</span>
                <strong>{formatNumber(stats.total_characters)}</strong>
              </div>
              <div>
                <span>角色档案</span>
                <strong>{formatNumber(stats.characters)}</strong>
              </div>
              <div>
                <span>世界观文档</span>
                <strong>{formatNumber(stats.world_documents)}</strong>
              </div>
              <div>
                <span>大纲节点</span>
                <strong>{formatNumber(stats.outline_items)}</strong>
              </div>
              <div>
                <span>完成大纲</span>
                <strong>{formatNumber(stats.completed_outline_items)}</strong>
              </div>
              <div>
                <span>已回收伏笔</span>
                <strong>{formatNumber(stats.paid_off_foreshadow_items)} / {formatNumber(stats.foreshadow_items)}</strong>
              </div>
            </section>
          )}

          {stats && (
            <section className="overview-progress-panel">
              <div>
                <header>
                  <span>章节进度</span>
                  <strong>{formatNumber(stats.completed_chapters)} / {formatNumber(overview.target_chapters || 0)}</strong>
                </header>
                <div className="overview-progress-track">
                  <span style={{ width: percent(stats.chapter_progress) }} />
                </div>
              </div>
              <div>
                <header>
                  <span>字数进度</span>
                  <strong>{formatNumber(stats.total_characters)} / {formatNumber(overview.target_characters || 0)}</strong>
                </header>
                <div className="overview-progress-track">
                  <span style={{ width: percent(stats.character_progress) }} />
                </div>
              </div>
              <div>
                <header>
                  <span>大纲完成度</span>
                  <strong>{formatNumber(stats.completed_outline_items)} / {formatNumber(stats.outline_items)}</strong>
                </header>
                <div className="overview-progress-track">
                  <span style={{ width: percent(stats.outline_progress) }} />
                </div>
              </div>
              <div>
                <header>
                  <span>伏笔回收度</span>
                  <strong>{formatNumber(stats.paid_off_foreshadow_items)} / {formatNumber(stats.foreshadow_items)}</strong>
                </header>
                <div className="overview-progress-track">
                  <span style={{ width: percent(stats.foreshadow_progress) }} />
                </div>
              </div>
            </section>
          )}

          <section className="overview-section">
            <header>
              <h3>章节进度</h3>
              <span>{overview.chapters.length} 个文件</span>
            </header>
            {overview.chapters.length === 0 ? (
              <p className="overview-muted">还没有章节正文。</p>
            ) : (
              <div className="overview-chapter-list">
                {overview.chapters.map((chapter) => (
                  <button key={chapter.path} onClick={() => onOpenFile(chapter.path)}>
                    <span>{chapter.title}</span>
                    <em>{chapter.path}</em>
                    <strong>{formatNumber(chapter.characters)} 字符</strong>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="overview-section">
            <header>
              <h3>世界观文件</h3>
              <span>{overview.world_documents.length} 个文件</span>
            </header>
            {overview.world_documents.length === 0 ? (
              <p className="overview-muted">还没有世界观文档。</p>
            ) : (
              <div className="overview-file-list">
                {overview.world_documents.map((path) => (
                  <button key={path} onClick={() => onOpenFile(path)}>{path}</button>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
