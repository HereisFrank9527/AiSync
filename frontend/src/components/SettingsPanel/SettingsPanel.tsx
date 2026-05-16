import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import type { Preset, LLMParams, AgentBehavior, ToolDescriptor } from "../../types";
import { checkLatestRelease, formatAssetSize, openExternalUrl, type UpdateInfo } from "../../config/updateCheck";
import "./SettingsPanel.css";

const PROVIDERS = ["anthropic", "openai", "custom"] as const;
const EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;

interface SettingsPanelProps {
  presets: Preset[];
  activeId: string;
  activePreset: Preset | null;
  onSelect: (id: string) => void;
  onCreate: (data: { name: string }) => Promise<Preset>;
  onCopy: (id: string, data?: { name?: string | null }) => Promise<Preset>;
  onUpdate: (
    id: string,
    data: { name?: string; llm?: LLMParams; behavior?: AgentBehavior },
  ) => Promise<Preset>;
  onListModels: (llm: LLMParams) => Promise<{ models: string[] }>;
  onDelete: (id: string) => Promise<void>;
  isBuiltin: (id: string) => boolean;
  tools: ToolDescriptor[];
}

export default function SettingsPanel({
  presets,
  activeId,
  activePreset,
  onSelect,
  onCreate,
  onCopy,
  onUpdate,
  onListModels,
  onDelete,
  isBuiltin,
  tools,
}: SettingsPanelProps) {
  const [llm, setLlm] = useState<LLMParams | null>(null);
  const [behavior, setBehavior] = useState<AgentBehavior | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [showRename, setShowRename] = useState(false);
  const [renameName, setRenameName] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState("");
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [updateError, setUpdateError] = useState("");
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState("");
  const [diagnosticsMessage, setDiagnosticsMessage] = useState("");
  const [activeSectionId, setActiveSectionId] = useState("profile");

  useEffect(() => {
    if (!activePreset) return;
    setLlm({ ...activePreset.llm });
    setBehavior({
      ...activePreset.behavior,
      enabled_tools: activePreset.behavior.enabled_tools ?? null,
    });
    setRenameName(activePreset.name);
    setMessage("");
    setIsError(false);
    setShowRename(false);
  }, [activePreset]);

  useEffect(() => {
    if (!llm) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setModelLoading(true);
      setModelError("");
      void onListModels(llm)
        .then((result) => {
          if (cancelled) return;
          setModelOptions(result.models);
        })
        .catch(() => {
          if (cancelled) return;
          setModelOptions([]);
          setModelError("无法获取模型列表");
        })
        .finally(() => {
          if (!cancelled) setModelLoading(false);
        });
    }, 500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [llm?.provider, llm?.api_key, llm?.api_key_env, llm?.api_base, onListModels]);

  if (!activePreset || !llm || !behavior) {
    return <p className="settings-loading">加载配置中…</p>;
  }

  const readonly = isBuiltin(activePreset.id);

  const patchLlm = (k: keyof LLMParams, v: unknown) =>
    setLlm((p) => (p ? { ...p, [k]: v } : p));

  const enabledTools = behavior.enabled_tools;
  const allToolsEnabled = enabledTools == null;

  const setAllToolsEnabled = (enabled: boolean) => {
    setBehavior((current) => current ? {
      ...current,
      enabled_tools: enabled ? null : tools.map((tool) => tool.name),
    } : current);
  };

  const toggleTool = (name: string, checked: boolean) => {
    setBehavior((current) => {
      if (!current) return current;
      const currentTools = current.enabled_tools ?? tools.map((tool) => tool.name);
      const next = checked
        ? Array.from(new Set([...currentTools, name]))
        : currentTools.filter((toolName) => toolName !== name);
      return { ...current, enabled_tools: next };
    });
  };

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

  const handleCopy = async () => {
    if (!activePreset) return;
    try {
      await onCopy(activePreset.id, { name: `${activePreset.name} 副本` });
      setIsError(false);
      setMessage("已复制");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setIsError(true);
      setMessage("复制失败");
    }
  };

  const handleRename = async () => {
    if (readonly) return;
    const name = renameName.trim();
    if (!name || name === activePreset.name) {
      setShowRename(false);
      return;
    }
    try {
      await onUpdate(activePreset.id, { name });
      setIsError(false);
      setMessage("已重命名");
      setTimeout(() => setMessage(""), 3000);
      setShowRename(false);
    } catch {
      setIsError(true);
      setMessage("重命名失败");
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

  const handleCheckUpdate = async () => {
    setCheckingUpdate(true);
    setUpdateError("");
    try {
      setUpdateInfo(await checkLatestRelease());
      setLastCheckedAt(new Date().toLocaleString());
    } catch (error) {
      setUpdateInfo(null);
      setUpdateError(error instanceof Error ? error.message : String(error));
    } finally {
      setCheckingUpdate(false);
    }
  };

  const preferredInstaller = updateInfo?.preferredAsset ?? null;

  const handleOpenInstaller = async () => {
    if (!preferredInstaller) return;
    const opened = await openExternalUrl(preferredInstaller.url);
    if (!opened) setUpdateError(`无法打开下载链接：${preferredInstaller.name}`);
  };

  const handleOpenRelease = async () => {
    if (!updateInfo) return;
    const opened = await openExternalUrl(updateInfo.releaseUrl);
    if (!opened) setUpdateError(`无法打开发布页：${updateInfo.releaseUrl}`);
  };

  const handleLoadDiagnostics = async () => {
    setDiagnosticsMessage("");
    try {
      const text = isTauri()
        ? await invoke<string>("backend_diagnostics")
        : "当前不在 Tauri 桌面环境，无法读取桌面诊断。";
      setDiagnostics(text);
    } catch (error) {
      setDiagnosticsMessage(`读取诊断失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const handleCopyDiagnostics = async () => {
    const text = diagnostics || (isTauri() ? await invoke<string>("backend_diagnostics") : "");
    if (!text) {
      setDiagnosticsMessage("没有可复制的诊断信息");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setDiagnostics(text);
      setDiagnosticsMessage("诊断信息已复制");
    } catch (error) {
      setDiagnosticsMessage(`复制失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const handleOpenLogDir = async () => {
    try {
      if (!isTauri()) {
        setDiagnosticsMessage("当前不在 Tauri 桌面环境，无法打开日志目录");
        return;
      }
      await invoke("open_log_dir");
      setDiagnosticsMessage("已打开日志目录");
    } catch (error) {
      setDiagnosticsMessage(`打开日志目录失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const canSaveSection = ["profile", "llm", "agent"].includes(activeSectionId);
  const updateSections = [
    {
      id: "profile",
      title: "预设管理",
      description: "管理当前 LLM 预设、复制、重命名和删除。",
      body: (
        <>
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
            <button className="btn-secondary" onClick={handleCopy}>
              复制
            </button>
            {!readonly && (
              <button className="btn-secondary" onClick={() => setShowRename(true)}>
                重命名
              </button>
            )}
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
              <button className="btn-ghost" onClick={() => { setShowNew(false); setNewName(""); }}>
                取消
              </button>
            </div>
          )}

          {showRename && !readonly && (
            <div className="preset-new-row">
              <input
                value={renameName}
                onChange={(e) => setRenameName(e.target.value)}
                placeholder="新预设名称"
                onKeyDown={(e) => e.key === "Enter" && handleRename()}
              />
              <button className="btn-primary" onClick={handleRename}>
                保存
              </button>
              <button className="btn-ghost" onClick={() => {
                setShowRename(false);
                setRenameName(activePreset.name);
              }}>
                取消
              </button>
            </div>
          )}

          {readonly && <p className="settings-hint">内置预设不可编辑，请新建预设后修改。</p>}
        </>
      ),
    },
    {
      id: "llm",
      title: "LLM 配置",
      description: "切换提供商、模型、API 地址和推理参数。",
      body: (
        <>
          <div className="settings-field">
            <label>Provider</label>
            <select value={llm.provider} onChange={(e) => patchLlm("provider", e.target.value)} disabled={readonly}>
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
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
            <input value={llm.api_key_env} onChange={(e) => patchLlm("api_key_env", e.target.value)} disabled={readonly} />
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
              list="llm-model-options"
            />
            <datalist id="llm-model-options">
              {modelOptions.map((model) => <option key={model} value={model} />)}
            </datalist>
            <div className="settings-field-hint">
              <span>{modelLoading ? "自动获取模型列表中…" : modelOptions.length ? `已获取 ${modelOptions.length} 个模型` : "输入框会自动补全可用模型"}</span>
              <button
                className="btn-ghost"
                type="button"
                onClick={() => llm && void onListModels(llm)
                  .then((result) => {
                    setModelOptions(result.models);
                    setModelError("");
                  })
                  .catch(() => setModelError("无法获取模型列表"))}
              >
                刷新模型
              </button>
            </div>
            {modelError && <p className="settings-msg error">{modelError}</p>}
          </div>
          <div className="settings-grid-2">
            <div className="settings-field">
              <label>Max Tokens</label>
              <input type="number" value={llm.max_tokens} onChange={(e) => patchLlm("max_tokens", Number(e.target.value))} disabled={readonly} />
            </div>
            <div className="settings-field">
              <label>Effort</label>
              <select value={llm.effort} onChange={(e) => patchLlm("effort", e.target.value)} disabled={readonly}>
                {EFFORTS.map((e) => <option key={e} value={e}>{e}</option>)}
              </select>
            </div>
          </div>
          <label className="settings-checkbox">
            <input type="checkbox" checked={llm.enable_thinking} onChange={(e) => patchLlm("enable_thinking", e.target.checked)} disabled={readonly} />
            启用思考模式
          </label>
          <p className="settings-hint">
            DeepSeek V4 等支持 thinking 的模型会按此开关发送 enabled/disabled；如果工具调用中遇到 reasoning_content 400，可先关闭后保存再重试。
          </p>
          <label className="settings-checkbox">
            <input type="checkbox" checked={llm.prompt_cache} onChange={(e) => patchLlm("prompt_cache", e.target.checked)} disabled={readonly} />
            Prompt Cache
          </label>
        </>
      ),
    },
    {
      id: "agent",
      title: "Agent 行为",
      description: "控制系统提示词、工具权限和主 Agent 默认行为。",
      body: (
        <>
          <div className="settings-field">
            <label>System Prompt（留空使用默认）</label>
            <textarea
              className="settings-textarea"
              rows={6}
              value={behavior.system_prompt ?? ""}
              onChange={(e) => setBehavior((b) => b ? { ...b, system_prompt: e.target.value || null } : b)}
              disabled={readonly}
              placeholder="自定义 system prompt…"
            />
          </div>
          <div className="settings-field">
            <label>主 Agent 可调用工具</label>
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={allToolsEnabled}
                onChange={(event) => setAllToolsEnabled(event.target.checked)}
                disabled={readonly}
              />
              默认全部工具可调用
            </label>
            {!allToolsEnabled && (
              <div className="settings-tools-grid">
                {tools.map((tool) => (
                  <label className="settings-tool-toggle" key={tool.name}>
                    <input
                      type="checkbox"
                      checked={(enabledTools ?? []).includes(tool.name)}
                      onChange={(event) => toggleTool(tool.name, event.target.checked)}
                      disabled={readonly}
                    />
                    <span>
                      <strong>{tool.name}</strong>
                      <em>{tool.description}</em>
                    </span>
                  </label>
                ))}
                {tools.length === 0 && <p className="settings-hint">工具列表尚未加载。</p>}
              </div>
            )}
          </div>
        </>
      ),
    },
    {
      id: "update",
      title: "应用更新",
      description: "检查 GitHub Releases 最新版本，优先打开 NSIS 安装包。",
      body: (
        <>
          <div className="settings-update-panel">
            <div>
              <strong>当前版本：{__AISYNC_APP_VERSION__}</strong>
              <p>当前轻量更新模式只检查新版本并打开下载页，不会后台静默安装。</p>
              {lastCheckedAt && <p>上次检查：{lastCheckedAt}</p>}
            </div>
            <button className="btn-secondary" onClick={handleCheckUpdate} disabled={checkingUpdate}>
              {checkingUpdate ? "检查中…" : "检查更新"}
            </button>
          </div>
          {updateInfo && (
            <div className={`settings-update-result${updateInfo.hasUpdate ? " has-update" : ""}`}>
              <strong>
              {updateInfo.hasUpdate ? `发现新版本 ${updateInfo.latestVersion}` : `已是最新版本 ${updateInfo.currentVersion}`}
              </strong>
              <span>发布：{updateInfo.releaseName}</span>
              {updateInfo.publishedAt && <span>时间：{new Date(updateInfo.publishedAt).toLocaleString()}</span>}
              <span>安装包：{preferredInstaller ? `${preferredInstaller.name} · ${formatAssetSize(preferredInstaller.size)}` : "未找到可下载资产"}</span>
              <span>资产数：{updateInfo.assets.length}</span>
              {updateInfo.body && <p>{updateInfo.body.slice(0, 260)}</p>}
              <div className="settings-update-actions">
                {preferredInstaller && (
                  <button className="btn-primary" type="button" onClick={() => void handleOpenInstaller()}>
                    下载安装包
                  </button>
                )}
                <button className="btn-secondary" type="button" onClick={() => void handleOpenRelease()}>
                  打开发布页
                </button>
              </div>
            </div>
          )}
          {updateError && <p className="settings-msg error">{updateError}</p>}
        </>
      ),
    },
    {
      id: "diagnostics",
      title: "诊断与日志",
      description: "复制安装版诊断信息，或打开本机日志目录。",
      body: (
        <>
          <div className="settings-diagnostics-actions">
            <button className="btn-secondary" type="button" onClick={() => void handleLoadDiagnostics()}>
              读取诊断
            </button>
            <button className="btn-secondary" type="button" onClick={() => void handleCopyDiagnostics()}>
              复制诊断
            </button>
            <button className="btn-secondary" type="button" onClick={() => void handleOpenLogDir()}>
              打开日志目录
            </button>
          </div>
          <p className="settings-hint">
            诊断包含版本、资源目录、后端端口、健康检查、随包 Python 和关键日志状态；不包含 API Key。
          </p>
          {diagnosticsMessage && <p className={`settings-msg${diagnosticsMessage.includes("失败") ? " error" : ""}`}>{diagnosticsMessage}</p>}
          {diagnostics && <pre className="settings-diagnostics">{diagnostics}</pre>}
        </>
      ),
    },
  ];
  const activeSection = updateSections.find((section) => section.id === activeSectionId) ?? updateSections[0];

  return (
    <div className="settings-panel">
      <header className="settings-header">
        <h2>设置</h2>
      </header>

      <div className="settings-body">
        <aside className="settings-inner-nav" aria-label="设置分类">
          {updateSections.map((section) => (
            <button
              key={section.id}
              className={activeSection.id === section.id ? "active" : ""}
              onClick={() => setActiveSectionId(section.id)}
            >
              <strong>{section.title}</strong>
              <span>{section.description}</span>
            </button>
          ))}
        </aside>

        <main className="settings-page">
          <section className="settings-card">
            <header className="settings-card-header">
              <div>
                <h3>{activeSection.title}</h3>
                <p>{activeSection.description}</p>
              </div>
            </header>
            <div className="settings-card-body">{activeSection.body}</div>
          </section>

          {!readonly && canSaveSection && (
            <section className="settings-save-panel">
              <div className="settings-card-body">
                <div className="settings-actions">
                  <button className="btn-primary" onClick={handleSave} disabled={saving}>
                  {saving ? "保存中…" : "保存设置"}
                </button>
                <button className="btn-secondary" onClick={handleReset} disabled={saving}>
                  重置
                </button>
                </div>
                {message && <p className={`settings-msg${isError ? " error" : ""}`}>{message}</p>}
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
