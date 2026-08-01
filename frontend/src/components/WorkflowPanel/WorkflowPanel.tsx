import { useEffect, useState } from "react";
import type { ChapterBatchWorkflowCreate, Preset, PromptPack, WorkflowRunCreate, WorkflowRunRecord, WorkflowRunStatus, WorkflowStepKind, WorkflowStepRecord, WorkflowStepUpdate, WorkflowTemplate } from "../../types";
import "./WorkflowPanel.css";

interface WorkflowPanelProps {
  runs: WorkflowRunRecord[];
  activeRun: WorkflowRunRecord | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onCreateChapterDraft: () => Promise<void>;
  onCreateChapterBatch: (data: ChapterBatchWorkflowCreate) => Promise<unknown>;
  onCreateFromTemplate: (templateId: string, data?: { title?: string; input_summary?: string }) => Promise<unknown>;
  onCreateCustom: (data: WorkflowRunCreate) => Promise<unknown>;
  onSelectRun: (runId: string) => void;
  onUpdateStatus: (runId: string, status: WorkflowRunStatus) => Promise<unknown>;
  onUpdateRun: (runId: string, data: Partial<Pick<WorkflowRunRecord, "title" | "input_summary" | "metadata">> & { status?: WorkflowRunStatus }) => Promise<unknown>;
  onUpdateStep: (runId: string, stepId: string, data: WorkflowStepUpdate) => Promise<unknown>;
  onAddStep: (runId: string, data: Partial<WorkflowStepRecord> & { name: string }) => Promise<unknown>;
  onDeleteStep: (runId: string, stepId: string) => Promise<unknown>;
  onResetStep: (runId: string, stepId: string) => Promise<unknown>;
  onSkipStep: (runId: string, stepId: string) => Promise<unknown>;
  onDeleteRun: (runId: string) => Promise<unknown>;
  onRunNext: (runId: string) => Promise<unknown>;
  onRunContinuous: (runId: string) => Promise<unknown>;
  onPause: (runId: string) => Promise<unknown>;
  onConfirm: (runId: string) => Promise<unknown>;
  executingRunId: string | null;
  continuousRunId: string | null;
  presets: Preset[];
  templates: WorkflowTemplate[];
  promptPacks: PromptPack[];
}

const runStatusLabels: Record<WorkflowRunStatus, string> = {
  draft: "草稿",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const stepStatusLabels: Record<WorkflowStepRecord["status"], string> = {
  pending: "待处理",
  running: "运行中",
  waiting_user: "待确认",
  completed: "完成",
  failed: "失败",
  skipped: "跳过",
};

function formatTime(value: string | null) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

export default function WorkflowPanel({
  runs,
  activeRun,
  loading,
  error,
  onRefresh,
  onCreateChapterDraft,
  onCreateChapterBatch,
  onCreateFromTemplate,
  onCreateCustom,
  onSelectRun,
  onUpdateStatus,
  onUpdateRun,
  onUpdateStep,
  onAddStep,
  onDeleteStep,
  onResetStep,
  onSkipStep,
  onDeleteRun,
  onRunNext,
  onRunContinuous,
  onPause,
  onConfirm,
  executingRunId,
  continuousRunId,
  presets,
  templates,
  promptPacks,
}: WorkflowPanelProps) {
  const currentStep = activeRun?.steps.find((step) => step.step_id === activeRun.current_step_id) ?? null;
  const canConfirm = currentStep?.kind === "user_confirm" && currentStep.status === "waiting_user";
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [stepDraft, setStepDraft] = useState<{
    presetId: string;
    outputPath: string;
    sourcePath: string;
    targetPath: string;
    extraPrompt: string;
    outputContent: string;
    promptPackIds: string[];
    overwriteExisting: boolean;
  } | null>(null);
  const [customDraft, setCustomDraft] = useState({
    title: "自定义工作流",
    inputSummary: "",
  });
  const [newStepDraft, setNewStepDraft] = useState<{ name: string; kind: WorkflowStepKind }>({
    name: "新增步骤",
    kind: "custom",
  });
  const [runDraft, setRunDraft] = useState({ title: "", inputSummary: "" });
  const [batchDraft, setBatchDraft] = useState({
    startChapter: 1,
    endChapter: 3,
    volume: "vol-01",
    requirements: "",
    presetId: "",
    targetCharacters: 3000,
    overwriteExisting: false,
  });
  const [creatingBatch, setCreatingBatch] = useState(false);
  const [batchError, setBatchError] = useState("");

  useEffect(() => {
    setRunDraft({
      title: activeRun?.title ?? "",
      inputSummary: activeRun?.input_summary ?? "",
    });
  }, [activeRun?.run_id, activeRun?.title, activeRun?.input_summary]);

  useEffect(() => {
    if (!activeRun || !editingStepId) {
      setStepDraft(null);
      return;
    }
    const step = activeRun.steps.find((item) => item.step_id === editingStepId);
    if (!step) {
      setEditingStepId(null);
      setStepDraft(null);
      return;
    }
    setStepDraft({
      presetId: step.preset_id ?? "",
      outputPath: step.output_path ?? "",
      sourcePath: typeof step.input.source_path === "string" ? step.input.source_path : "",
      targetPath: typeof step.input.target_path === "string" ? step.input.target_path : "",
      extraPrompt: typeof step.input.extra_prompt === "string" ? step.input.extra_prompt : "",
      outputContent: typeof step.output.content === "string" ? step.output.content : "",
      promptPackIds: [...step.prompt_pack_ids],
      overwriteExisting: step.input.overwrite_existing === true,
    });
  }, [activeRun, editingStepId]);

  const startEditStep = (step: WorkflowStepRecord) => {
    setEditingStepId(step.step_id);
    setStepDraft({
      presetId: step.preset_id ?? "",
      outputPath: step.output_path ?? "",
      sourcePath: typeof step.input.source_path === "string" ? step.input.source_path : "",
      targetPath: typeof step.input.target_path === "string" ? step.input.target_path : "",
      extraPrompt: typeof step.input.extra_prompt === "string" ? step.input.extra_prompt : "",
      outputContent: typeof step.output.content === "string" ? step.output.content : "",
      promptPackIds: [...step.prompt_pack_ids],
      overwriteExisting: step.input.overwrite_existing === true,
    });
  };

  const saveStepDraft = async (step: WorkflowStepRecord) => {
    if (!activeRun || !stepDraft) return;
    await onUpdateStep(activeRun.run_id, step.step_id, {
      preset_id: stepDraft.presetId || null,
      prompt_pack_ids: stepDraft.promptPackIds,
      output_path: stepDraft.outputPath || null,
      input: {
        ...step.input,
        extra_prompt: stepDraft.extraPrompt,
        source_path: stepDraft.sourcePath,
        target_path: stepDraft.targetPath,
        overwrite_existing: stepDraft.overwriteExisting,
      },
      output: { ...step.output, content: stepDraft.outputContent },
    });
    setEditingStepId(null);
  };

  const promptPackName = (packId: string) => promptPacks.find((pack) => pack.id === packId)?.name ?? packId;

  const recommendedPromptPacksForStep = (step: WorkflowStepRecord) => {
    const stageByKind: Partial<Record<WorkflowStepKind, string>> = {
      plan: "chapter_plan",
      draft: "chapter_draft",
      revise: "revision",
      check: "check",
      chapter: "chapter_draft",
    };
    const stage = stageByKind[step.kind];
    if (!stage) return [];
    const categoryPriority: Partial<Record<WorkflowStepKind, string[]>> = {
      plan: ["planning", "writing"],
      draft: ["style", "writing", "special"],
      revise: ["revision", "style", "writing"],
      check: ["check"],
      chapter: ["style", "writing", "special"],
    };
    const priorities = categoryPriority[step.kind] ?? [];
    return promptPacks
      .filter((pack) => pack.enabled && pack.content.trim() && pack.stages.includes(stage as never))
      .sort((a, b) => {
        const ai = priorities.includes(a.category) ? priorities.indexOf(a.category) : priorities.length;
        const bi = priorities.includes(b.category) ? priorities.indexOf(b.category) : priorities.length;
        return ai - bi || a.name.localeCompare(b.name, "zh-Hans-CN");
      });
  };

  const injectedPromptPackLabel = (step: WorkflowStepRecord) => {
    const raw = step.output.prompt_packs;
    if (!raw || typeof raw !== "object") return "";
    const names = (raw as { names?: unknown }).names;
    if (!Array.isArray(names)) return "无";
    const text = names.filter((item): item is string => typeof item === "string" && item.length > 0).join("、");
    return text || "无";
  };

  const injectedPromptPackMeta = (step: WorkflowStepRecord) => {
    const raw = step.output.prompt_packs;
    if (!raw || typeof raw !== "object") return "";
    const record = raw as Record<string, unknown>;
    const mode = record.mode === "step_selected" ? "手动选择" : "阶段默认";
    const stage = typeof record.stage === "string" ? record.stage : "";
    const count = typeof record.count === "number" ? record.count : 0;
    const promptChars = typeof record.prompt_chars === "number" ? ` · Prompt ${record.prompt_chars} 字符` : "";
    const extra = record.extra_prompt_included ? " · 含额外要求" : "";
    return `${mode}${stage ? ` · ${stage}` : ""} · ${count} 个${extra}${promptChars}`;
  };

  const applyRecommendedPromptPacks = (step: WorkflowStepRecord) => {
    const recommended = recommendedPromptPacksForStep(step);
    setStepDraft((current) => current ? { ...current, promptPackIds: recommended.map((pack) => pack.id) } : current);
  };

  const toggleStepPromptPack = (packId: string, checked: boolean) => {
    setStepDraft((current) => {
      if (!current) return current;
      const next = checked
        ? Array.from(new Set([...current.promptPackIds, packId]))
        : current.promptPackIds.filter((id) => id !== packId);
      return { ...current, promptPackIds: next };
    });
  };

  const createCustomWorkflow = async () => {
    await onCreateCustom({
      workflow_type: "custom",
      title: customDraft.title,
      input_summary: customDraft.inputSummary,
      steps: [],
      metadata: { source: "manual_custom", version: 1 },
    });
  };

  const addStep = async () => {
    if (!activeRun) return;
    await onAddStep(activeRun.run_id, {
      name: newStepDraft.name.trim() || "新增步骤",
      kind: newStepDraft.kind,
      status: "pending",
      input: {},
      output: {},
    });
  };

  const createChapterBatch = async () => {
    setBatchError("");
    if (!Number.isInteger(batchDraft.startChapter) || !Number.isInteger(batchDraft.endChapter)) {
      setBatchError("请输入有效的起始章和结束章");
      return;
    }
    if (batchDraft.endChapter < batchDraft.startChapter) {
      setBatchError("结束章节不能小于起始章节");
      return;
    }
    if (batchDraft.endChapter - batchDraft.startChapter + 1 > 20) {
      setBatchError("单次最多连续写 20 章");
      return;
    }
    if (!Number.isFinite(batchDraft.targetCharacters) || batchDraft.targetCharacters < 500 || batchDraft.targetCharacters > 20000) {
      setBatchError("每章目标字数需在 500 到 20000 之间");
      return;
    }
    setCreatingBatch(true);
    try {
      await onCreateChapterBatch({
        start_chapter: batchDraft.startChapter,
        end_chapter: batchDraft.endChapter,
        volume: batchDraft.volume,
        requirements: batchDraft.requirements,
        preset_id: batchDraft.presetId || null,
        target_characters: batchDraft.targetCharacters,
        overwrite_existing: batchDraft.overwriteExisting,
      });
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : "无法创建连续章节任务");
    } finally {
      setCreatingBatch(false);
    }
  };

  const deleteRun = async () => {
    if (!activeRun) return;
    if (!window.confirm(`确定删除工作流记录「${activeRun.title}」？`)) return;
    await onDeleteRun(activeRun.run_id);
  };

  const deleteStep = async (step: WorkflowStepRecord) => {
    if (!activeRun) return;
    if (!window.confirm(`确定删除步骤「${step.name}」？`)) return;
    await onDeleteStep(activeRun.run_id, step.step_id);
  };

  const saveRunDraft = async () => {
    if (!activeRun) return;
    await onUpdateRun(activeRun.run_id, {
      title: runDraft.title,
      input_summary: runDraft.inputSummary,
    });
  };

  const resetStep = async (step: WorkflowStepRecord) => {
    if (!activeRun) return;
    await onResetStep(activeRun.run_id, step.step_id);
  };

  const skipStep = async (step: WorkflowStepRecord) => {
    if (!activeRun) return;
    await onSkipStep(activeRun.run_id, step.step_id);
  };

  const chapterSteps = activeRun?.steps.filter((step) => step.kind === "chapter") ?? [];
  const completedChapters = chapterSteps.filter((step) => step.status === "completed").length;
  const chapterProgress = chapterSteps.length > 0 ? Math.round((completedChapters / chapterSteps.length) * 100) : 0;
  const currentChapter = currentStep?.kind === "chapter" && typeof currentStep.input.chapter_number === "number"
    ? currentStep.input.chapter_number
    : null;
  const isExecuting = executingRunId === activeRun?.run_id;
  const isContinuous = continuousRunId === activeRun?.run_id;

  return (
    <div className="workflow-panel">
      <header className="workflow-header">
        <div>
          <h2>工作流</h2>
          <p>章节任务、检查点与模型分工。</p>
        </div>
        <div className="workflow-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-primary" onClick={() => void onCreateChapterDraft()}>新建章节草稿流程</button>
        </div>
      </header>

      {error && <p className="workflow-error">{error}</p>}

      <div className="workflow-layout">
        <aside className="workflow-list">
          <div className="workflow-list-header">
            <strong>运行记录</strong>
            <span>{loading ? "加载中…" : `${runs.length} 条`}</span>
          </div>
          {runs.length === 0 && !loading && <p className="workflow-muted">暂无工作流记录。</p>}
          {runs.map((run) => (
            <button
              key={run.run_id}
              className={activeRun?.run_id === run.run_id ? "active" : ""}
              onClick={() => onSelectRun(run.run_id)}
            >
              <strong>{run.title}</strong>
              <span>{runStatusLabels[run.status]} · {run.workflow_type}</span>
              <em>{formatTime(run.updated_at)}</em>
            </button>
          ))}
        </aside>

        <main className="workflow-detail">
          <section className="workflow-batch-create">
            <div className="workflow-batch-heading">
              <div>
                <strong>连续写章</strong>
                <span>每章独立保存，失败停在当前章。</span>
              </div>
              <span className="workflow-batch-limit">最多 20 章</span>
            </div>
            <div className="workflow-batch-grid">
              <label>
                起始章
                <input
                  type="number"
                  min={1}
                  max={9999}
                  value={batchDraft.startChapter}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, startChapter: Number(event.target.value) }))}
                />
              </label>
              <label>
                结束章
                <input
                  type="number"
                  min={1}
                  max={9999}
                  value={batchDraft.endChapter}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, endChapter: Number(event.target.value) }))}
                />
              </label>
              <label>
                卷目录
                <input
                  value={batchDraft.volume}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, volume: event.target.value }))}
                  placeholder="vol-01"
                />
              </label>
              <label>
                每章目标字数
                <input
                  type="number"
                  min={500}
                  max={20000}
                  step={500}
                  value={batchDraft.targetCharacters}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, targetCharacters: Number(event.target.value) }))}
                />
              </label>
              <label className="workflow-batch-model">
                写作模型
                <select
                  value={batchDraft.presetId}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, presetId: event.target.value }))}
                >
                  <option value="">使用默认模型</option>
                  {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
                </select>
              </label>
              <label className="workflow-batch-requirements">
                通用写作要求
                <textarea
                  rows={3}
                  value={batchDraft.requirements}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, requirements: event.target.value }))}
                  placeholder="本批章节的目标、节奏或必须发生的事件"
                />
              </label>
            </div>
            <div className="workflow-batch-actions">
              <label className="workflow-inline-check">
                <input
                  type="checkbox"
                  checked={batchDraft.overwriteExisting}
                  onChange={(event) => setBatchDraft((current) => ({ ...current, overwriteExisting: event.target.checked }))}
                />
                覆盖已存在章节
              </label>
              <button className="btn-primary" disabled={creatingBatch} onClick={() => void createChapterBatch()}>
                {creatingBatch ? "正在创建…" : "创建连续章节任务"}
              </button>
            </div>
            {batchError && <p className="workflow-batch-error">{batchError}</p>}
          </section>

          {templates.length > 0 && (
            <section className="workflow-template-strip">
              <div>
                <strong>工作流示例</strong>
                <span>从模板创建后可以编辑每一步。</span>
              </div>
              <div className="workflow-template-list">
                {templates.map((template) => (
                  <button key={template.id} onClick={() => void onCreateFromTemplate(template.id)}>
                    <strong>{template.name}</strong>
                    <span>{template.description}</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="workflow-custom-create">
            <div>
              <strong>自定义工作流</strong>
              <span>从空白记录开始，之后自行添加步骤。</span>
            </div>
            <input
              value={customDraft.title}
              onChange={(event) => setCustomDraft((current) => ({ ...current, title: event.target.value }))}
              placeholder="工作流标题"
            />
            <input
              value={customDraft.inputSummary}
              onChange={(event) => setCustomDraft((current) => ({ ...current, inputSummary: event.target.value }))}
              placeholder="任务摘要"
            />
            <button className="btn-secondary" onClick={() => void createCustomWorkflow()}>创建空白流程</button>
          </section>

          {!activeRun && (
            <div className="workflow-empty">
              <strong>选择一个工作流</strong>
              <p>这里会显示步骤、模型预设、提示词包、输出位置和错误信息。</p>
            </div>
          )}

          {activeRun && (
            <>
              <section className="workflow-summary">
                <div>
                  <div className="workflow-run-editor">
                    <input
                      value={runDraft.title}
                      onChange={(event) => setRunDraft((current) => ({ ...current, title: event.target.value }))}
                      placeholder="工作流标题"
                    />
                    <input
                      value={runDraft.inputSummary}
                      onChange={(event) => setRunDraft((current) => ({ ...current, inputSummary: event.target.value }))}
                      placeholder="任务摘要"
                    />
                    <button className="btn-secondary" onClick={() => void saveRunDraft()}>保存标题摘要</button>
                  </div>
                </div>
                <span className={`workflow-status status-${activeRun.status}`}>{runStatusLabels[activeRun.status]}</span>
              </section>

              <div className="workflow-toolbar">
                <button
                  className="btn-primary"
                  disabled={isExecuting || activeRun.status === "completed" || activeRun.status === "cancelled"}
                  onClick={() => void onRunContinuous(activeRun.run_id)}
                >
                  {isContinuous
                    ? (currentChapter ? `正在写第 ${currentChapter} 章…` : "连续执行中…")
                    : activeRun.status === "paused" ? "继续执行" : "连续执行"}
                </button>
                <button
                  className="btn-secondary"
                  disabled={isExecuting || activeRun.status === "completed" || activeRun.status === "cancelled"}
                  onClick={() => void onRunNext(activeRun.run_id)}
                >
                  只运行下一步
                </button>
                {canConfirm && (
                  <button className="btn-primary" onClick={() => void onConfirm(activeRun.run_id)}>确认并继续</button>
                )}
                <button className="btn-secondary" disabled={!isExecuting && activeRun.status === "paused"} onClick={() => void onPause(activeRun.run_id)}>
                  {isExecuting ? "完成当前步后暂停" : "暂停"}
                </button>
                {activeRun.workflow_type !== "chapter_batch" && (
                  <button className="btn-secondary" onClick={() => void onUpdateStatus(activeRun.run_id, "completed")}>完成</button>
                )}
                <button className="btn-danger" onClick={() => void onUpdateStatus(activeRun.run_id, "cancelled")}>取消</button>
                <button className="btn-danger" onClick={() => void deleteRun()}>删除记录</button>
              </div>

              {chapterSteps.length > 0 && (
                <section className="workflow-progress" aria-label="连续章节进度">
                  <div>
                    <strong>{completedChapters} / {chapterSteps.length} 章</strong>
                    <span>{currentChapter ? `当前第 ${currentChapter} 章` : runStatusLabels[activeRun.status]}</span>
                  </div>
                  <div className="workflow-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={chapterProgress}>
                    <span style={{ width: `${chapterProgress}%` }} />
                  </div>
                </section>
              )}

              <section className="workflow-add-step">
                <input
                  value={newStepDraft.name}
                  onChange={(event) => setNewStepDraft((current) => ({ ...current, name: event.target.value }))}
                  placeholder="步骤名称"
                />
                <select
                  value={newStepDraft.kind}
                  onChange={(event) => setNewStepDraft((current) => ({ ...current, kind: event.target.value as WorkflowStepKind }))}
                >
                  <option value="context">检索上下文</option>
                  <option value="plan">生成计划</option>
                  <option value="user_confirm">人工确认</option>
                  <option value="draft">生成草稿</option>
                  <option value="revise">修订草稿</option>
                  <option value="check">检查</option>
                  <option value="write_file">写入正式章节</option>
                  <option value="chapter">连续章节检查点</option>
                  <option value="custom">自定义</option>
                </select>
                <button className="btn-secondary" onClick={() => void addStep()}>添加步骤</button>
              </section>

              <section className="workflow-steps">
                {activeRun.steps.map((step, index) => (
                  <article
                    key={step.step_id}
                    className={`workflow-step${activeRun.current_step_id === step.step_id ? " current" : ""}`}
                  >
                    <div className="workflow-step-index">{index + 1}</div>
                    <div className="workflow-step-body">
                      <header>
                        <strong>{step.name}</strong>
                        <span>{stepStatusLabels[step.status]} · {step.kind}</span>
                      </header>
                      <div className="workflow-step-meta">
                        {step.preset_id && <span>模型：{step.preset_id}</span>}
                        {step.prompt_pack_ids.length > 0 && <span>提示词：{step.prompt_pack_ids.map(promptPackName).join("、")}</span>}
                        {injectedPromptPackLabel(step) && (
                          <span>已注入：{injectedPromptPackLabel(step)}</span>
                        )}
                        {injectedPromptPackMeta(step) && <span>{injectedPromptPackMeta(step)}</span>}
                        {step.context_pack_ids.length > 0 && <span>上下文：{step.context_pack_ids.length} 个</span>}
                        {step.output_path && <span>输出：{step.output_path}</span>}
                        {step.error && <span className="workflow-step-error">错误：{step.error}</span>}
                      </div>
                      <div className="workflow-step-actions">
                        <button className="btn-secondary" onClick={() => startEditStep(step)}>编辑步骤</button>
                        <button className="btn-secondary" onClick={() => void resetStep(step)}>重试此步</button>
                        <button className="btn-secondary" onClick={() => void skipStep(step)}>跳过此步</button>
                        <button className="btn-danger" onClick={() => void deleteStep(step)}>删除步骤</button>
                      </div>
                      {editingStepId === step.step_id && stepDraft && (
                        <div className="workflow-step-editor">
                          <label>
                            步骤模型
                            <select
                              value={stepDraft.presetId}
                              onChange={(event) => setStepDraft((current) => current ? { ...current, presetId: event.target.value } : current)}
                            >
                              <option value="">使用默认模型</option>
                              {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
                            </select>
                          </label>
                          <label>
                            输出路径
                            <input
                              value={stepDraft.outputPath}
                              onChange={(event) => setStepDraft((current) => current ? { ...current, outputPath: event.target.value } : current)}
                              placeholder="例如 temp/drafts/ch-001.md"
                            />
                          </label>
                          {step.kind === "write_file" && (
                            <>
                              <label>
                                草稿来源
                                <input
                                  value={stepDraft.sourcePath}
                                  onChange={(event) => setStepDraft((current) => current ? { ...current, sourcePath: event.target.value } : current)}
                                  placeholder="留空则使用最近一次草稿输出，例如 temp/drafts/xxx.md"
                                />
                              </label>
                              <label>
                                正式章节路径
                                <input
                                  value={stepDraft.targetPath}
                                  onChange={(event) => setStepDraft((current) => current ? { ...current, targetPath: event.target.value } : current)}
                                  placeholder="例如 chapters/vol-01/ch-001.md"
                                />
                              </label>
                            </>
                          )}
                          {step.kind === "chapter" && (
                            <>
                              <label>
                                正式章节路径
                                <input value={stepDraft.targetPath} disabled />
                              </label>
                              <label className="workflow-inline-check">
                                <input
                                  type="checkbox"
                                  checked={stepDraft.overwriteExisting}
                                  onChange={(event) => setStepDraft((current) => current ? { ...current, overwriteExisting: event.target.checked } : current)}
                                />
                                允许覆盖这一章
                              </label>
                            </>
                          )}
                          <label>
                            提示词包
                            <div className="workflow-prompt-pack-toolbar">
                              <button className="btn-secondary" type="button" onClick={() => applyRecommendedPromptPacks(step)}>
                                套用推荐
                              </button>
                              <button
                                className="btn-ghost"
                                type="button"
                                onClick={() => setStepDraft((current) => current ? { ...current, promptPackIds: [] } : current)}
                              >
                                清空
                              </button>
                              <span>
                                {recommendedPromptPacksForStep(step).length > 0
                                  ? `推荐 ${recommendedPromptPacksForStep(step).length} 个`
                                  : "当前步骤暂无推荐"}
                              </span>
                            </div>
                            <div className="workflow-prompt-pack-grid">
                              {promptPacks.map((pack) => (
                                <label key={pack.id} className="workflow-prompt-pack-option">
                                  <input
                                    type="checkbox"
                                    checked={stepDraft.promptPackIds.includes(pack.id)}
                                    onChange={(event) => toggleStepPromptPack(pack.id, event.target.checked)}
                                  />
                                  <span>
                                    <strong>{pack.name}</strong>
                                    <em>{pack.category} · {pack.stages.join(", ")}</em>
                                  </span>
                                </label>
                              ))}
                              {promptPacks.length === 0 && <p className="workflow-muted">还没有可用提示词包，可先到设置页创建。</p>}
                            </div>
                          </label>
                          <p className="workflow-editor-hint">
                            不勾选时使用当前步骤阶段默认提示词包；勾选后本步骤只使用所选提示词包。
                          </p>
                          <label>
                            额外提示词
                            <textarea
                              value={stepDraft.extraPrompt}
                              onChange={(event) => setStepDraft((current) => current ? { ...current, extraPrompt: event.target.value } : current)}
                              placeholder="只作用于当前步骤的临时要求"
                              rows={4}
                            />
                          </label>
                          <label>
                            步骤输出
                            <textarea
                              value={stepDraft.outputContent}
                              onChange={(event) => setStepDraft((current) => current ? { ...current, outputContent: event.target.value } : current)}
                              placeholder="可编辑计划或草稿内容"
                              rows={6}
                            />
                          </label>
                          <div className="workflow-step-editor-actions">
                            <button className="btn-primary" onClick={() => void saveStepDraft(step)}>保存步骤</button>
                            <button className="btn-secondary" onClick={() => setEditingStepId(null)}>取消</button>
                          </div>
                        </div>
                      )}
                      {typeof step.output.content === "string" && (
                        <pre className="workflow-step-output">{step.output.content.slice(0, 1200)}</pre>
                      )}
                      {typeof step.output.summary === "string" && (
                        <p className="workflow-step-summary">{step.output.summary}</p>
                      )}
                    </div>
                  </article>
                ))}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
