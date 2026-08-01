import { useEffect, useState } from "react";
import type { Preset, LLMParams, AgentBehavior, ModelListResponse, ToolDescriptor, ProjectPromptPackSettings, ProjectSystemRules, PromptPack, PromptPackCategory, PromptPackExample, PromptPackScope, PromptPackStage } from "../../types";
import { checkLatestRelease, formatAssetSize, openExternalUrl, type UpdateInfo } from "../../config/updateCheck";
import { getApiBase } from "../../config/runtime";
import "./SettingsPanel.css";

const PROVIDERS = ["anthropic", "openai", "custom"] as const;
const EFFORTS: Array<{ id: LLMParams["effort"]; label: string }> = [
  { id: "low", label: "低" },
  { id: "medium", label: "中" },
  { id: "high", label: "高" },
  { id: "xhigh", label: "超高" },
  { id: "max", label: "最高" },
];
const CONTEXT_WINDOWS: Array<{
  id: LLMParams["context_window"];
  label: string;
  description: string;
}> = [
  { id: "economy", label: "经济", description: "少量历史和检索片段，适合闲聊、省 token。" },
  { id: "standard", label: "标准", description: "默认窗口，适合日常写作和设定问答。" },
  { id: "long", label: "长上下文", description: "扩大历史和项目片段，适合写正文、大改章节。" },
  { id: "maximum", label: "最高上下文", description: "尽量拉满可用上下文，消耗高，需模型本身支持大窗口。" },
];
const PROMPT_CATEGORIES: Array<{ id: PromptPackCategory; label: string }> = [
  { id: "style", label: "文风" },
  { id: "writing", label: "写作" },
  { id: "planning", label: "规划" },
  { id: "revision", label: "润色" },
  { id: "check", label: "检查" },
  { id: "special", label: "特殊片段" },
  { id: "custom", label: "自定义" },
];
const PROMPT_STAGES: Array<{ id: PromptPackStage; label: string }> = [
  { id: "chat", label: "对话" },
  { id: "chapter_plan", label: "章节规划" },
  { id: "chapter_draft", label: "章节草稿" },
  { id: "revision", label: "润色" },
  { id: "check", label: "检查" },
  { id: "special", label: "特殊片段" },
];

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
  onListModels: (llm: LLMParams) => Promise<ModelListResponse>;
  onDelete: (id: string) => Promise<void>;
  isBuiltin: (id: string) => boolean;
  tools: ToolDescriptor[];
  promptPacks: {
    packs: PromptPack[];
    examples: PromptPackExample[];
    projectSettings: ProjectPromptPackSettings;
    loading: boolean;
    error: string;
    create: (data: {
      name: string;
      category?: PromptPackCategory;
      scope?: PromptPackScope;
      stages?: PromptPackStage[];
      content?: string;
      enabled?: boolean;
      description?: string;
    }) => Promise<PromptPack>;
    update: (id: string, data: Partial<{
      name: string;
      category: PromptPackCategory;
      scope: PromptPackScope;
      stages: PromptPackStage[];
      content: string;
      enabled: boolean;
      description: string;
    }>) => Promise<PromptPack>;
    copy: (id: string, name?: string | null) => Promise<PromptPack>;
    createFromExample: (exampleId: string) => Promise<PromptPack>;
    remove: (id: string) => Promise<void>;
    updateProjectSettings: (settings: ProjectPromptPackSettings) => Promise<ProjectPromptPackSettings>;
  };
  systemRules: {
    settings: ProjectSystemRules;
    loading: boolean;
    error: string;
    update: (settings: Pick<ProjectSystemRules, "mode" | "content">) => Promise<ProjectSystemRules>;
  };
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
  promptPacks,
  systemRules,
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
  const [activePromptPackId, setActivePromptPackId] = useState<string | null>(null);
  const [activePromptExampleId, setActivePromptExampleId] = useState<string | null>(null);
  const [promptDraft, setPromptDraft] = useState<PromptPack | null>(null);
  const [systemRuleDraft, setSystemRuleDraft] = useState<ProjectSystemRules>(systemRules.settings);

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
          if (result.error) setModelError(result.error);
        })
        .catch((error) => {
          if (cancelled) return;
          setModelOptions([]);
          setModelError(error instanceof Error ? error.message : "无法获取模型列表");
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

  useEffect(() => {
    if (promptPacks.loading) return;
    const target = promptPacks.packs.find((pack) => pack.id === activePromptPackId) ?? promptPacks.packs[0] ?? null;
    setActivePromptPackId(target?.id ?? null);
    setPromptDraft(target ? { ...target, stages: [...target.stages] } : null);
  }, [activePromptPackId, promptPacks.loading, promptPacks.packs]);

  useEffect(() => {
    if (promptPacks.loading) return;
    if (!promptPacks.examples.length) {
      setActivePromptExampleId(null);
      return;
    }
    if (!activePromptExampleId || !promptPacks.examples.some((example) => example.id === activePromptExampleId)) {
      setActivePromptExampleId(promptPacks.examples[0].id);
    }
  }, [activePromptExampleId, promptPacks.examples, promptPacks.loading]);

  useEffect(() => {
    setSystemRuleDraft(systemRules.settings);
  }, [systemRules.settings]);

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

  const refreshModels = async () => {
    if (!llm) return;
    setModelLoading(true);
    setModelError("");
    try {
      const result = await onListModels(llm);
      setModelOptions(result.models);
      if (result.error) setModelError(result.error);
    } catch (error) {
      setModelOptions([]);
      setModelError(error instanceof Error ? error.message : "无法获取模型列表");
    } finally {
      setModelLoading(false);
    }
  };

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
      const healthUrl = getApiBase().replace(/\/api$/, "/health");
      let health = "unknown";
      try {
        const response = await fetch(healthUrl, { cache: "no-store" });
        health = `${response.status} ${response.ok ? "ok" : "failed"}`;
      } catch (error) {
        health = error instanceof Error ? error.message : String(error);
      }
      setDiagnostics([
        `version=${__AISYNC_APP_VERSION__}`,
        `mode=web`,
        `url=${window.location.href}`,
        `api_base=${getApiBase()}`,
        `health_url=${healthUrl}`,
        `health=${health}`,
        `user_agent=${navigator.userAgent}`,
      ].join("\n"));
    } catch (error) {
      setDiagnosticsMessage(`读取诊断失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const handleCopyDiagnostics = async () => {
    const text = diagnostics || [
      `version=${__AISYNC_APP_VERSION__}`,
      `mode=web`,
      `url=${window.location.href}`,
      `api_base=${getApiBase()}`,
      `user_agent=${navigator.userAgent}`,
    ].join("\n");
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

  const handleCreatePromptPack = async () => {
    try {
      const pack = await promptPacks.create({
        name: "新的提示词",
        category: "style",
        scope: "global",
        stages: ["chat", "chapter_draft"],
        content: "在这里写入可复用的文风、写作规则或特殊要求。",
        enabled: true,
        description: "",
      });
      setActivePromptPackId(pack.id);
      setPromptDraft(pack);
    } catch {
      setIsError(true);
      setMessage("创建提示词失败");
    }
  };

  const handleCreatePromptPackExample = async () => {
    const exampleId = activePromptExampleId;
    if (!exampleId) return;
    try {
      const pack = await promptPacks.createFromExample(exampleId);
      setActivePromptPackId(pack.id);
      setPromptDraft(pack);
      setIsError(false);
      setMessage("已从示例创建提示词");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setIsError(true);
      setMessage("创建示例提示词失败");
    }
  };

  const handleSavePromptPack = async () => {
    if (!promptDraft) return;
    try {
      const pack = await promptPacks.update(promptDraft.id, {
        name: promptDraft.name,
        category: promptDraft.category,
        scope: promptDraft.scope,
        stages: promptDraft.stages,
        content: promptDraft.content,
        enabled: promptDraft.enabled,
        description: promptDraft.description,
      });
      setPromptDraft(pack);
      setIsError(false);
      setMessage("提示词已保存");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setIsError(true);
      setMessage("保存提示词失败");
    }
  };

  const handleCopyPromptPack = async () => {
    if (!promptDraft) return;
    try {
      const pack = await promptPacks.copy(promptDraft.id, `${promptDraft.name} 副本`);
      setActivePromptPackId(pack.id);
      setPromptDraft(pack);
    } catch {
      setIsError(true);
      setMessage("复制提示词失败");
    }
  };

  const handleDeletePromptPack = async () => {
    if (!promptDraft) return;
    if (!window.confirm(`确定删除提示词「${promptDraft.name}」？`)) return;
    try {
      await promptPacks.remove(promptDraft.id);
      setActivePromptPackId(null);
      setPromptDraft(null);
    } catch {
      setIsError(true);
      setMessage("删除提示词失败");
    }
  };

  const patchPromptDraft = <K extends keyof PromptPack>(key: K, value: PromptPack[K]) => {
    setPromptDraft((current) => current ? { ...current, [key]: value } : current);
  };

  const togglePromptStage = (stage: PromptPackStage, checked: boolean) => {
    setPromptDraft((current) => {
      if (!current) return current;
      const next = checked
        ? Array.from(new Set([...current.stages, stage]))
        : current.stages.filter((item) => item !== stage);
      return { ...current, stages: next.length ? next : ["chat"] };
    });
  };

  const updateProjectPromptSettings = async (settings: ProjectPromptPackSettings) => {
    try {
      await promptPacks.updateProjectSettings(settings);
      setIsError(false);
      setMessage("项目提示词设置已保存");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setIsError(true);
      setMessage("保存项目提示词设置失败");
    }
  };

  const handleSaveSystemRules = async () => {
    try {
      const saved = await systemRules.update({
        mode: "project",
        content: systemRuleDraft.content,
      });
      setSystemRuleDraft(saved);
      setIsError(false);
      setMessage("AGENT.md 已保存");
      setTimeout(() => setMessage(""), 3000);
    } catch {
      setIsError(true);
      setMessage("保存 AGENT.md 失败");
    }
  };

  const toggleProjectPromptPack = (packId: string, checked: boolean) => {
    const current = promptPacks.projectSettings.enabled_pack_ids;
    const next = checked
      ? Array.from(new Set([...current, packId]))
      : current.filter((id) => id !== packId);
    void updateProjectPromptSettings({ ...promptPacks.projectSettings, mode: "project", enabled_pack_ids: next });
  };

  const canSaveSection = ["profile", "llm", "search", "agent"].includes(activeSectionId);
  const activePromptExample = promptPacks.examples.find((example) => example.id === activePromptExampleId) ?? null;
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
            <div className="settings-model-picker">
              <input
                value={llm.model_name}
                onChange={(e) => patchLlm("model_name", e.target.value)}
                disabled={readonly}
                placeholder="手动输入模型名"
              />
              <select
                value={modelOptions.includes(llm.model_name) ? llm.model_name : ""}
                onChange={(event) => event.target.value && patchLlm("model_name", event.target.value)}
                disabled={readonly || modelOptions.length === 0}
                title={modelOptions.length === 0 ? "暂无可选模型，请先刷新模型列表" : "从已获取模型中选择"}
              >
                <option value="">{modelOptions.length === 0 ? "暂无模型列表" : "选择模型"}</option>
                {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            </div>
            <div className="settings-field-hint">
              <span>{modelLoading ? "获取模型列表中…" : modelOptions.length ? `已获取 ${modelOptions.length} 个模型，可用右侧下拉选择` : "可手动输入模型名，或点击刷新模型拉取列表"}</span>
              <button
                className="btn-ghost"
                type="button"
                onClick={() => void refreshModels()}
                disabled={modelLoading}
              >
                {modelLoading ? "刷新中" : "刷新模型"}
              </button>
            </div>
            {modelError && <p className="settings-msg error settings-model-error">{modelError}</p>}
          </div>
          <div className="settings-grid-2">
            <div className="settings-field">
              <label>Max Tokens</label>
              <input type="number" value={llm.max_tokens} onChange={(e) => patchLlm("max_tokens", Number(e.target.value))} disabled={readonly} />
            </div>
            <div className="settings-field">
              <label>请求超时（秒）</label>
              <input
                type="number"
                min={5}
                value={llm.request_timeout}
                onChange={(e) => patchLlm("request_timeout", Math.max(5, Number(e.target.value) || 120))}
                disabled={readonly}
              />
            </div>
          </div>
          <div className="settings-grid-2">
            <div className="settings-field">
              <label>思考强度</label>
              <select value={llm.effort} onChange={(e) => patchLlm("effort", e.target.value)} disabled={readonly}>
                {EFFORTS.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
              </select>
            </div>
          </div>
          <p className="settings-hint">
            控制支持推理的模型投入多少思考预算。不同供应商的可用级别不同，AiSync 会自动映射；普通模型可能忽略此设置。
          </p>
          <div className="settings-field">
            <label>上下文窗口</label>
            <div className="settings-context-window-grid">
              {CONTEXT_WINDOWS.map((item) => (
                <label
                  key={item.id}
                  className={`settings-context-window-option${llm.context_window === item.id ? " active" : ""}`}
                >
                  <input
                    type="radio"
                    checked={llm.context_window === item.id}
                    onChange={() => patchLlm("context_window", item.id)}
                    disabled={readonly}
                  />
                  <span>
                    <strong>{item.label}</strong>
                    <em>{item.description}</em>
                  </span>
                </label>
              ))}
            </div>
            <p className="settings-hint">
              这个选项控制本轮注入的历史消息、检索片段和片段长度；不是输出长度。最高上下文会明显增加输入 token。
            </p>
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
      id: "search",
      title: "联网搜索",
      description: "配置 Tavily、免费搜索和供应商原生搜索的使用顺序与预算。",
      body: (
        <>
          <label className="settings-checkbox">
            <input
              type="checkbox"
              checked={llm.native_web_search}
              onChange={(e) => patchLlm("native_web_search", e.target.checked)}
              disabled={readonly}
            />
            允许 Agent 调用联网搜索
          </label>
          <p className="settings-hint">
            默认关闭。开启后 Agent 才会看到 web_search 工具；普通对话不会自动联网。
          </p>

          <div className="settings-field">
            <label>搜索策略</label>
            <select
              value={llm.web_search_provider}
              onChange={(e) => patchLlm("web_search_provider", e.target.value)}
              disabled={readonly}
            >
              <option value="auto">自动：Tavily → Bing RSS → 模型原生</option>
              <option value="tavily">Tavily 优先：失败后自动降级</option>
              <option value="bing">仅 Bing RSS 免费搜索</option>
              <option value="native">仅供应商原生搜索</option>
            </select>
            <p className="settings-hint">
              推荐使用自动。Tavily 能返回更相关的正文片段；Bing RSS 只适合发现页面；模型原生搜索取决于具体 API 是否透传来源。
            </p>
          </div>

          {(llm.web_search_provider === "auto" || llm.web_search_provider === "tavily") && (
            <>
              <div className="settings-field">
                <label>Tavily API Key</label>
                <input
                  type="password"
                  value={llm.tavily_api_key ?? ""}
                  onChange={(e) => patchLlm("tavily_api_key", e.target.value || null)}
                  placeholder="tvly-...；留空则读取环境变量"
                  disabled={readonly}
                />
                <p className="settings-hint">密钥与 LLM Key 一样保存在本机预设文件，不会显示在 Agent 日志或来源卡中。</p>
              </div>
              <div className="settings-field">
                <label>Tavily Key 环境变量（备用）</label>
                <input
                  value={llm.tavily_api_key_env}
                  onChange={(e) => patchLlm("tavily_api_key_env", e.target.value)}
                  disabled={readonly}
                />
              </div>
              <div className="settings-grid-2">
                <div className="settings-field">
                  <label>搜索深度</label>
                  <select
                    value={llm.tavily_search_depth}
                    onChange={(e) => patchLlm("tavily_search_depth", e.target.value)}
                    disabled={readonly}
                  >
                    <option value="basic">Basic · 1 credit</option>
                    <option value="advanced">Advanced · 2 credits</option>
                  </select>
                </div>
                <div className="settings-field">
                  <label>最多结果数</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={llm.web_search_max_results}
                    onChange={(e) => patchLlm("web_search_max_results", Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
                    disabled={readonly}
                  />
                </div>
              </div>
              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={llm.tavily_include_raw_content}
                  onChange={(e) => patchLlm("tavily_include_raw_content", e.target.checked)}
                  disabled={readonly}
                />
                请求清洗后的网页正文
              </label>
              <p className="settings-hint">
                默认关闭。开启后能获得更多细节，但响应更慢、注入 Agent 的上下文更长；通常先使用 Advanced 片段即可。
              </p>
            </>
          )}

          <p className="settings-hint">
            工具中心如果为 web_search 指定了默认 LLM 预设，联网策略和 Tavily Key 将读取那个工具预设，而不是当前对话预设。
          </p>
        </>
      ),
    },
    {
      id: "agent",
      title: "Agent 行为",
      description: "控制工具权限和预设级 Agent 兼容设置。",
      body: (
        <>
          <div className="settings-field">
            <label>预设 System Prompt（高级兼容，留空使用默认）</label>
            <textarea
              className="settings-textarea"
              rows={6}
              value={behavior.system_prompt ?? ""}
              onChange={(e) => setBehavior((b) => b ? { ...b, system_prompt: e.target.value || null } : b)}
              disabled={readonly}
              placeholder="自定义 system prompt…"
            />
            <p className="settings-hint">
              这里属于 LLM 预设级覆盖。当前项目长期使用的工作习惯和文风请到“AGENT.md”页维护。
            </p>
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
      id: "system-rules",
      title: "AGENT.md",
      description: "维护当前项目长期使用的工作习惯和文风。",
      body: (
        <div className="settings-system-rules">
          <div className="settings-project-prompts">
            <strong>项目根目录 / AGENT.md</strong>
            <span>{systemRuleDraft.mode === "project" ? "已启用" : "尚未创建，保存后自动创建"}</span>
            <span>每轮 Agent 对话都会读取，当前 {systemRuleDraft.content.trim().length} 字符</span>
          </div>

          <div className="settings-field">
            <label>长期工作习惯与当前文风</label>
            <textarea
              className="settings-textarea settings-system-rule-textarea"
              rows={14}
              value={systemRuleDraft.content}
              onChange={(event) => setSystemRuleDraft((current) => ({ ...current, content: event.target.value }))}
              placeholder="例如：避免连续单句成段；修改正式文件前先检索相关设定。"
            />
            <p className="settings-hint">
              当前项目固定采用的文风可以直接写在这里。需要跨项目复用、随时切换的文风仍放在“提示词管理”。Agent 也可以通过文件改动差异预览更新本文件。
            </p>
          </div>

          <details className="settings-system-rule-default">
            <summary>
              <strong>AGENT.md 基础模板</strong>
              <span>可展开参考或恢复模板</span>
            </summary>
            <pre>{systemRuleDraft.default_content}</pre>
            <button
              className="btn-secondary"
              type="button"
              onClick={() => setSystemRuleDraft((current) => ({ ...current, content: current.default_content }))}
            >
              恢复基础模板
            </button>
          </details>

          <div className="settings-actions">
            <button className="btn-primary" type="button" onClick={() => void handleSaveSystemRules()}>
              保存 AGENT.md
            </button>
            <button
              className="btn-secondary"
              type="button"
              onClick={() => setSystemRuleDraft(systemRules.settings)}
            >
              重置
            </button>
          </div>
          {systemRules.loading && <p className="settings-hint">加载 AGENT.md 中…</p>}
          {systemRules.error && <p className="settings-msg error">{systemRules.error}</p>}
          {message && activeSectionId === "system-rules" && <p className={`settings-msg${isError ? " error" : ""}`}>{message}</p>}
        </div>
      ),
    },
    {
      id: "prompts",
      title: "提示词管理",
      description: "维护可复用的文风、写作规则、检查规则和特殊片段提示词。",
      body: (
        <div className="settings-prompt-manager">
          <div className="settings-prompt-sidebar">
            <div className="settings-prompt-actions">
              <button className="btn-primary" onClick={() => void handleCreatePromptPack()}>新建提示词</button>
            </div>
            <div className="settings-project-prompts">
              <strong>当前项目使用方式</strong>
              <label className="settings-radio">
                <input
                  type="radio"
                  checked={promptPacks.projectSettings.mode === "global"}
                  onChange={() => void updateProjectPromptSettings({ ...promptPacks.projectSettings, mode: "global" })}
                />
                沿用全局启用
              </label>
              <label className="settings-radio">
                <input
                  type="radio"
                  checked={promptPacks.projectSettings.mode === "project"}
                  onChange={() => void updateProjectPromptSettings({ ...promptPacks.projectSettings, mode: "project" })}
                />
                只使用本项目勾选项
              </label>
              <span>
                {promptPacks.projectSettings.mode === "project"
                  ? `已为本项目选择 ${promptPacks.projectSettings.enabled_pack_ids.length} 个提示词`
                  : "所有已启用提示词会按阶段自动生效"}
              </span>
            </div>
            {promptPacks.loading && <p className="settings-hint">加载提示词中…</p>}
            {promptPacks.error && <p className="settings-msg error">{promptPacks.error}</p>}
            {!promptPacks.loading && promptPacks.packs.length === 0 && (
              <p className="settings-hint">还没有提示词。可以先新建一个“文风”提示词。</p>
            )}
            <div className="settings-prompt-examples">
              <div className="settings-prompt-examples-header">
                <strong>提示词示例</strong>
                <span>先预览，再创建</span>
              </div>
              <div className="settings-prompt-example-grid">
                {promptPacks.examples.map((example) => (
                  <button
                    key={example.id}
                    className={example.id === activePromptExampleId ? "active" : ""}
                    onClick={() => setActivePromptExampleId(example.id)}
                  >
                    <strong>{example.name}</strong>
                    <span>{example.description}</span>
                  </button>
                ))}
                {promptPacks.examples.length === 0 && <p className="settings-hint">暂无示例。</p>}
              </div>
              {activePromptExample && (
                <div className="settings-prompt-example-preview">
                  <div>
                    <strong>{activePromptExample.name}</strong>
                    <span>{PROMPT_CATEGORIES.find((item) => item.id === activePromptExample.category)?.label ?? activePromptExample.category}</span>
                  </div>
                  <p>{activePromptExample.description}</p>
                  <pre>{activePromptExample.content}</pre>
                  <button className="btn-primary" onClick={() => void handleCreatePromptPackExample()}>
                    从示例创建
                  </button>
                </div>
              )}
            </div>
            <div className="settings-prompt-list">
              {promptPacks.packs.map((pack) => (
                <button
                  key={pack.id}
                  className={pack.id === activePromptPackId ? "active" : ""}
                  onClick={() => {
                    setActivePromptPackId(pack.id);
                    setPromptDraft({ ...pack, stages: [...pack.stages] });
                  }}
                >
                  <strong>{pack.name}</strong>
                  <span>{PROMPT_CATEGORIES.find((item) => item.id === pack.category)?.label ?? pack.category} · {pack.enabled ? "启用" : "停用"}</span>
                  {promptPacks.projectSettings.mode === "project" && (
                    <em>{promptPacks.projectSettings.enabled_pack_ids.includes(pack.id) ? "本项目使用" : "本项目未选"}</em>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="settings-prompt-editor">
            {promptDraft ? (
              <>
                <div className="settings-grid-2">
                  <div className="settings-field">
                    <label>名称</label>
                    <input value={promptDraft.name} onChange={(event) => patchPromptDraft("name", event.target.value)} />
                  </div>
                  <div className="settings-field">
                    <label>分类</label>
                    <select value={promptDraft.category} onChange={(event) => patchPromptDraft("category", event.target.value as PromptPackCategory)}>
                      {PROMPT_CATEGORIES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select>
                  </div>
                </div>
                <div className="settings-grid-2">
                  <div className="settings-field">
                    <label>范围标记</label>
                    <select value={promptDraft.scope} onChange={(event) => patchPromptDraft("scope", event.target.value as PromptPackScope)}>
                      <option value="global">全局</option>
                      <option value="project">项目</option>
                    </select>
                  </div>
                  <div className="settings-field">
                    <label>当前项目</label>
                    <label className="settings-checkbox settings-project-prompt-toggle">
                      <input
                        type="checkbox"
                        checked={promptPacks.projectSettings.enabled_pack_ids.includes(promptDraft.id)}
                        onChange={(event) => toggleProjectPromptPack(promptDraft.id, event.target.checked)}
                      />
                      本项目使用这个提示词
                    </label>
                  </div>
                </div>
                <div className="settings-field">
                  <label>描述</label>
                  <input
                    value={promptDraft.description}
                    onChange={(event) => patchPromptDraft("description", event.target.value)}
                    placeholder="例如：主线文风、战斗段落、伏笔检查规则"
                  />
                </div>
                <label className="settings-checkbox">
                  <input
                    type="checkbox"
                    checked={promptDraft.enabled}
                    onChange={(event) => patchPromptDraft("enabled", event.target.checked)}
                  />
                  启用这个提示词
                </label>
                <div className="settings-field">
                  <label>适用阶段</label>
                  <div className="settings-prompt-stage-grid">
                    {PROMPT_STAGES.map((stage) => (
                      <label className="settings-checkbox" key={stage.id}>
                        <input
                          type="checkbox"
                          checked={promptDraft.stages.includes(stage.id)}
                          onChange={(event) => togglePromptStage(stage.id, event.target.checked)}
                        />
                        {stage.label}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="settings-field">
                  <label>提示词正文</label>
                  <textarea
                    className="settings-textarea settings-prompt-textarea"
                    rows={14}
                    value={promptDraft.content}
                    onChange={(event) => patchPromptDraft("content", event.target.value)}
                    placeholder="写入长期可复用的文风、叙事规则、禁忌、特殊模型片段要求等。"
                  />
                </div>
                <div className="settings-actions">
                  <button className="btn-primary" onClick={() => void handleSavePromptPack()}>保存提示词</button>
                  <button className="btn-secondary" onClick={() => void handleCopyPromptPack()}>复制</button>
                  <button className="btn-danger" onClick={() => void handleDeletePromptPack()}>删除</button>
                </div>
                {message && <p className={`settings-msg${isError ? " error" : ""}`}>{message}</p>}
              </>
            ) : (
              <div className="settings-empty-state">
                <strong>选择或新建一个提示词</strong>
                <p>这里适合保存长期文风、写作规则、章节草稿要求、润色标准和特殊片段提示词。</p>
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      id: "update",
      title: "应用更新",
      description: "检查 GitHub Releases 最新版本，打开发布资产或发布页。",
      body: (
        <>
          <div className="settings-update-panel">
            <div>
              <strong>当前版本：{__AISYNC_APP_VERSION__}</strong>
              <p>Web-only 模式只检查新版本并打开发布页，不会后台静默安装。</p>
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
              <span>发布资产：{preferredInstaller ? `${preferredInstaller.name} · ${formatAssetSize(preferredInstaller.size)}` : "未找到可下载资产"}</span>
              <span>资产数：{updateInfo.assets.length}</span>
              {updateInfo.body && <p>{updateInfo.body.slice(0, 260)}</p>}
              <div className="settings-update-actions">
                {preferredInstaller && (
                  <button className="btn-primary" type="button" onClick={() => void handleOpenInstaller()}>
                    打开下载
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
      title: "Web 诊断",
      description: "复制当前 Web 前端和后端连接信息。",
      body: (
        <>
          <div className="settings-diagnostics-actions">
            <button className="btn-secondary" type="button" onClick={() => void handleLoadDiagnostics()}>
              读取诊断
            </button>
            <button className="btn-secondary" type="button" onClick={() => void handleCopyDiagnostics()}>
              复制诊断
            </button>
          </div>
          <p className="settings-hint">
            诊断包含版本、当前地址、API 地址、健康检查和浏览器信息；不包含 API Key。
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
