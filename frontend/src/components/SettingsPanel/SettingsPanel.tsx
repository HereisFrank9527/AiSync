import { useEffect, useState } from "react";
import type { Preset, LLMParams, AgentBehavior } from "../../types";
import "./SettingsPanel.css";

const PROVIDERS = ["anthropic", "openai", "custom"] as const;
const EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;

interface SettingsPanelProps {
  presets: Preset[];
  activeId: string;
  activePreset: Preset | null;
  onSelect: (id: string) => void;
  onCreate: (data: { name: string }) => Promise<Preset>;
  onUpdate: (
    id: string,
    data: { name?: string; llm?: LLMParams; behavior?: AgentBehavior },
  ) => Promise<Preset>;
  onDelete: (id: string) => Promise<void>;
  isBuiltin: (id: string) => boolean;
}

export default function SettingsPanel({
  presets,
  activeId,
  activePreset,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
  isBuiltin,
}: SettingsPanelProps) {
  const [llm, setLlm] = useState<LLMParams | null>(null);
  const [behavior, setBehavior] = useState<AgentBehavior | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    if (!activePreset) return;
    setLlm({ ...activePreset.llm });
    setBehavior({ ...activePreset.behavior });
    setMessage("");
    setIsError(false);
  }, [activePreset]);

  if (!activePreset || !llm || !behavior) {
    return <p className="settings-loading">加载配置中…</p>;
  }

  const readonly = isBuiltin(activePreset.id);

  const patchLlm = (k: keyof LLMParams, v: unknown) =>
    setLlm((p) => (p ? { ...p, [k]: v } : p));

  const handleSave = async () => {
    if (readonly) return;
    setSaving(true);
    setMessage("");
    try {
      await onUpdate(activePreset.id, { llm, behavior });
      setIsError(false);
      setMessage("已保存");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setIsError(true);
      setMessage("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      await onCreate({ name });
      setNewName("");
      setShowNew(false);
    } catch {
      setIsError(true);
      setMessage("创建失败");
    }
  };

  const handleDelete = async () => {
    if (readonly) return;
    if (!window.confirm(`确定删除预设「${activePreset.name}」？`)) return;
    try {
      await onDelete(activePreset.id);
    } catch {
      setIsError(true);
      setMessage("删除失败");
    }
  };

  const handleReset = () => {
    if (!activePreset) return;
    setLlm({ ...activePreset.llm });
    setBehavior({ ...activePreset.behavior });
    setMessage("");
  };

  return (
    <div className="settings-panel">
      <header className="settings-header">
        <h2>设置</h2>
      </header>

      <div className="settings-body">
        {/* ── Preset selector ── */}
        <div className="settings-section">
          <h3>预设</h3>
          <div className="preset-bar">
            <select
              className="preset-select"
              value={activeId}
              onChange={(e) => onSelect(e.target.value)}
            >
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{isBuiltin(p.id) ? " (内置)" : ""}
                </option>
              ))}
            </select>
            <button className="btn-secondary" onClick={() => setShowNew(true)}>
              新建
            </button>
            {!readonly && (
              <button className="btn-danger" onClick={handleDelete}>
                删除
              </button>
            )}
          </div>

          {showNew && (
            <div className="preset-new-row">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="预设名称"
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
              <button className="btn-primary" onClick={handleCreate}>
                创建
              </button>
              <button
                className="btn-ghost"
                onClick={() => { setShowNew(false); setNewName(""); }}
              >
                取消
              </button>
            </div>
          )}

          {readonly && (
            <p className="settings-hint">内置预设不可编辑，请新建预设后修改。</p>
          )}
        </div>

        {/* ── LLM config ── */}
        <div className="settings-section">
          <h3>LLM 配置</h3>

          <div className="settings-field">
            <label>Provider</label>
            <select
              value={llm.provider}
              onChange={(e) => patchLlm("provider", e.target.value)}
              disabled={readonly}
            >
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div className="settings-field">
            <label>API Key</label>
            <input
              type="password"
              value={llm.api_key ?? ""}
              onChange={(e) => patchLlm("api_key", e.target.value || null)}
              placeholder="直接粘贴 API Key，留空则使用环境变量"
              disabled={readonly}
            />
          </div>

          <div className="settings-field">
            <label>API Key 环境变量（备用）</label>
            <input
              value={llm.api_key_env}
              onChange={(e) => patchLlm("api_key_env", e.target.value)}
              disabled={readonly}
            />
          </div>

          <div className="settings-field">
            <label>API Base URL</label>
            <input
              value={llm.api_base ?? ""}
              onChange={(e) => patchLlm("api_base", e.target.value || null)}
              placeholder="留空使用默认"
              disabled={readonly}
            />
          </div>

          <div className="settings-field">
            <label>模型名称</label>
            <input
              value={llm.model_name}
              onChange={(e) => patchLlm("model_name", e.target.value)}
              disabled={readonly}
            />
          </div>

          <div className="settings-field">
            <label>Max Tokens</label>
            <input
              type="number"
              value={llm.max_tokens}
              onChange={(e) => patchLlm("max_tokens", Number(e.target.value))}
              disabled={readonly}
            />
          </div>

          <div className="settings-field">
            <label>Effort</label>
            <select
              value={llm.effort}
              onChange={(e) => patchLlm("effort", e.target.value)}
              disabled={readonly}
            >
              {EFFORTS.map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
          </div>

          <label className="settings-checkbox">
            <input
              type="checkbox"
              checked={llm.enable_thinking}
              onChange={(e) => patchLlm("enable_thinking", e.target.checked)}
              disabled={readonly}
            />
            启用 Thinking
          </label>

          <label className="settings-checkbox">
            <input
              type="checkbox"
              checked={llm.prompt_cache}
              onChange={(e) => patchLlm("prompt_cache", e.target.checked)}
              disabled={readonly}
            />
            Prompt Cache
          </label>
        </div>

        {/* ── System Prompt ── */}
        <div className="settings-section">
          <h3>Agent 行为</h3>
          <div className="settings-field">
            <label>System Prompt（留空使用默认）</label>
            <textarea
              className="settings-textarea"
              rows={6}
              value={behavior.system_prompt ?? ""}
              onChange={(e) =>
                setBehavior((b) =>
                  b ? { ...b, system_prompt: e.target.value || null } : b,
                )
              }
              disabled={readonly}
              placeholder="自定义 system prompt…"
            />
          </div>
        </div>

        {/* ── Actions ── */}
        {!readonly && (
          <div className="settings-section">
            <div className="settings-actions">
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? "保存中…" : "保存设置"}
              </button>
              <button className="btn-secondary" onClick={handleReset} disabled={saving}>
                重置
              </button>
            </div>
            {message && (
              <p className={`settings-msg${isError ? " error" : ""}`}>{message}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
