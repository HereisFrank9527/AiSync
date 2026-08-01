import { useEffect, useMemo, useState } from "react";
import Drawer from "../common/Drawer";
import SchemaForm from "../SchemaForm";
import { AiRender, toolResultToRender } from "../AiRender";
import type { Preset, ToolDescriptor, ToolFileAccess, ToolRunRecord } from "../../types";
import "./ToolDrawer.css";

interface ToolDrawerProps {
  tool: ToolDescriptor | null;
  run: ToolRunRecord | null;
  initialParams?: Record<string, unknown> | null;
  error: string;
  running: boolean;
  presets: Preset[];
  activePresetId: string | null;
  onClose: () => void;
  onExecute: (name: string, params: Record<string, unknown>) => void | Promise<unknown>;
  onInvoke: (name: string, params: Record<string, unknown>, presetId?: string | null) => void | Promise<unknown>;
  onUpdateDefaultPreset: (name: string, presetId: string | null) => void | Promise<unknown>;
}

const runStatusLabels: Record<ToolRunRecord["status"], string> = {
  completed: "完成",
  failed: "失败",
};

function countAccess(access: ToolFileAccess) {
  return access.read.length + access.write.length + access.generate.length;
}

function needsFileImpactConfirmation(access: ToolFileAccess) {
  return access.write.length > 0 || access.generate.length > 0;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return date.toLocaleString();
}

function renderFileList(title: string, items: string[], tone: "read" | "write" | "generate") {
  if (!items.length) return null;
  return (
    <div className={`tool-file-group tool-file-group--${tone}`}>
      <strong>{title}<span>{items.length}</span></strong>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function FileAccessNotice({ access }: { access: ToolFileAccess }) {
  if (!access.read.length && !access.write.length && !access.generate.length) {
    return <p className="tool-muted">此工具未声明文件影响。</p>;
  }
  return (
    <section className="tool-file-access">
      <header>
        <h3>文件影响</h3>
        <span>{countAccess(access)} 条声明</span>
      </header>
      {renderFileList("读取", access.read, "read")}
      {renderFileList("修改", access.write, "write")}
      {renderFileList("生成", access.generate, "generate")}
    </section>
  );
}

function ParamsView({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params);
  if (!entries.length) return <p className="tool-muted">本次运行没有记录参数。</p>;
  return (
    <dl className="tool-run-params">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ToolSummary({ tool }: { tool: ToolDescriptor }) {
  const categoryLabels: Record<string, string> = {
    generate: "生成",
    edit: "编辑",
    patch: "改动包",
    manage: "管理",
    workspace: "工作区",
    search: "检索",
    review: "审查",
    other: "通用",
  };
  const writePolicyLabels: Record<string, string> = {
    none: "只读",
    direct: "直接写入",
    proposal: "待确认改动包",
    workspace_only: "仅打开工作区",
  };
  return (
    <section className="tool-summary">
      <p>{tool.description}</p>
      <div className="tool-summary-grid">
        <span>
          工具分类
          <strong>{categoryLabels[tool.governance?.category ?? "other"] ?? "通用"}</strong>
        </span>
        <span>
          写入策略
          <strong>{writePolicyLabels[tool.governance?.write_policy ?? "none"] ?? "未声明"}</strong>
        </span>
        <span>
          默认方案
          <strong>{tool.default_preset_id ?? "当前设置"}</strong>
        </span>
        <span>
          呈现方式
          <strong>{tool.presentation?.description ?? tool.presentation?.type ?? "未声明"}</strong>
        </span>
        <span>
          调用方式
          <strong>{tool.has_frontend_ui ? "表单 / AI" : "Agent"}</strong>
        </span>
      </div>
      {tool.governance?.agent_boundary && <p className="tool-muted">{tool.governance.agent_boundary}</p>}
    </section>
  );
}

export default function ToolDrawer({
  tool,
  run,
  initialParams,
  error,
  running,
  presets,
  activePresetId,
  onClose,
  onExecute,
  onInvoke,
  onUpdateDefaultPreset,
}: ToolDrawerProps) {
  const [fileImpactConfirmed, setFileImpactConfirmed] = useState(false);
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);
  const [savingDefaultPreset, setSavingDefaultPreset] = useState(false);
  const result = run?.result ?? null;
  const activeAccess = run?.file_access ?? tool?.file_access;
  const title = tool?.name ?? run?.tool_name ?? "工具";
  const requiresConfirmation = Boolean(tool && activeAccess && needsFileImpactConfirmation(activeAccess));
  const presetIds = useMemo(() => new Set(presets.map((preset) => preset.id)), [presets]);
  const fallbackPresetId = presetIds.has(activePresetId ?? "") ? activePresetId : presets[0]?.id ?? "default";
  const effectivePresetId = presetIds.has(selectedPresetId ?? "") ? selectedPresetId : fallbackPresetId;

  useEffect(() => {
    setFileImpactConfirmed(false);
    const preferred = tool?.default_preset_id ?? activePresetId ?? "default";
    setSelectedPresetId(presetIds.has(preferred) ? preferred : fallbackPresetId);
  }, [activePresetId, fallbackPresetId, presetIds, tool?.default_preset_id, tool?.name]);

  const runWithConfirmation = (
    action: (name: string, params: Record<string, unknown>, presetId?: string | null) => void | Promise<unknown>,
    name: string,
    params: Record<string, unknown>,
    presetId?: string | null,
  ) => {
    if (requiresConfirmation && !fileImpactConfirmed) return;
    return action(name, params, presetId);
  };

  const saveDefaultPreset = async (presetId: string | null) => {
    if (!tool) return;
    setSavingDefaultPreset(true);
    try {
      await onUpdateDefaultPreset(tool.name, presetId);
    } finally {
      setSavingDefaultPreset(false);
    }
  };

  return (
    <Drawer open={Boolean(tool) || Boolean(run)} title={title} onClose={onClose}>
      {(tool || run) && (
        <div className="tool-drawer">
          {tool && <ToolSummary tool={tool} />}
          {activeAccess && <FileAccessNotice access={activeAccess} />}

          {tool?.ui_schema ? (
            <section className="tool-form-panel">
              <header>
                <h3>执行参数</h3>
                <span>{running ? "运行中" : "待执行"}</span>
              </header>
              {requiresConfirmation && (
                <label className="tool-impact-confirm">
                  <input
                    type="checkbox"
                    checked={fileImpactConfirmed}
                    disabled={running}
                    onChange={(event) => setFileImpactConfirmed(event.target.checked)}
                  />
                  <span>我已确认此工具可能修改或生成上方声明的项目文件。</span>
                </label>
              )}
              {presets.length > 0 && (
                <div className="tool-preset-panel">
                  <label className="tool-preset-select">
                    <span>AI 生成方案</span>
                    <select
                      value={effectivePresetId ?? "default"}
                      disabled={running}
                      onChange={(event) => setSelectedPresetId(event.target.value)}
                    >
                      {presets.map((preset) => (
                        <option key={preset.id} value={preset.id}>
                          {preset.name}{preset.id === tool.default_preset_id ? " · 工具默认" : preset.id === activePresetId ? " · 当前设置" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="tool-preset-actions">
                    <button
                      className="btn-secondary"
                      type="button"
                      disabled={running || savingDefaultPreset}
                      onClick={() => void saveDefaultPreset(effectivePresetId)}
                    >
                      {savingDefaultPreset ? "保存中" : "设为工具默认"}
                    </button>
                    <button
                      className="btn-ghost"
                      type="button"
                      disabled={running || savingDefaultPreset || !tool.default_preset_id}
                      onClick={() => void saveDefaultPreset(null)}
                    >
                      清除默认
                    </button>
                  </div>
                </div>
              )}
              <SchemaForm
                schema={tool.ui_schema}
                disabled={running}
                actionsDisabled={requiresConfirmation && !fileImpactConfirmed}
                values={initialParams}
                submitLabel={running ? "执行中…" : "直接执行"}
                secondaryLabel="AI 生成"
                onSubmit={(params) => runWithConfirmation(onExecute, tool.name, params)}
                onSecondarySubmit={(params) => runWithConfirmation(onInvoke, tool.name, params, effectivePresetId)}
              />
              {requiresConfirmation && !fileImpactConfirmed && (
                <p className="tool-confirm-hint">执行前需要先勾选文件影响确认。</p>
              )}
            </section>
          ) : tool ? (
            <p className="tool-muted">这个工具暂未提供表单配置。</p>
          ) : null}

          {error && <div className="tool-error">{error}</div>}
          {run?.error && <div className="tool-error">{run.error}</div>}
          {run && (
            <section className="tool-run-meta">
              <span>{run.mode === "invoke" ? "AI 生成" : "直接执行"}</span>
              <span className={run.status === "completed" ? "is-success" : "is-error"}>{runStatusLabels[run.status]}</span>
              <span>{formatTime(run.finished_at)}</span>
            </section>
          )}
          {run && !tool && (
            <section className="tool-run-params-panel">
              <header>
                <h3>运行参数</h3>
                <span>{run.run_id}</span>
              </header>
              <ParamsView params={run.params} />
            </section>
          )}
          {result && (
            <section className="tool-result">
              <h3>结果</h3>
              <AiRender {...toolResultToRender(result)} />
            </section>
          )}
        </div>
      )}
    </Drawer>
  );
}
