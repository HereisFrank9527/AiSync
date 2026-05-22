import type { WorkflowRunRecord, WorkflowRunStatus, WorkflowStepRecord } from "../../types";
import "./WorkflowPanel.css";

interface WorkflowPanelProps {
  runs: WorkflowRunRecord[];
  activeRun: WorkflowRunRecord | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onCreateChapterDraft: () => Promise<void>;
  onSelectRun: (runId: string) => void;
  onUpdateStatus: (runId: string, status: WorkflowRunStatus) => Promise<unknown>;
  onRunNext: (runId: string) => Promise<unknown>;
  onConfirm: (runId: string) => Promise<unknown>;
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
  onSelectRun,
  onUpdateStatus,
  onRunNext,
  onConfirm,
}: WorkflowPanelProps) {
  const currentStep = activeRun?.steps.find((step) => step.step_id === activeRun.current_step_id) ?? null;
  const canConfirm = currentStep?.kind === "user_confirm" && currentStep.status === "waiting_user";

  return (
    <div className="workflow-panel">
      <header className="workflow-header">
        <div>
          <h2>工作流</h2>
          <p>多步骤写作任务的记录、暂停点和后续执行骨架。</p>
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
                  <h3>{activeRun.title}</h3>
                  <p>{activeRun.input_summary || "暂无输入摘要"}</p>
                </div>
                <span className={`workflow-status status-${activeRun.status}`}>{runStatusLabels[activeRun.status]}</span>
              </section>

              <div className="workflow-toolbar">
                <button className="btn-primary" onClick={() => void onRunNext(activeRun.run_id)}>运行下一步</button>
                {canConfirm && (
                  <button className="btn-primary" onClick={() => void onConfirm(activeRun.run_id)}>确认并继续</button>
                )}
                <button className="btn-secondary" onClick={() => void onUpdateStatus(activeRun.run_id, "paused")}>暂停</button>
                <button className="btn-secondary" onClick={() => void onUpdateStatus(activeRun.run_id, "completed")}>完成</button>
                <button className="btn-danger" onClick={() => void onUpdateStatus(activeRun.run_id, "cancelled")}>取消</button>
              </div>

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
                        {step.prompt_pack_ids.length > 0 && <span>提示词：{step.prompt_pack_ids.length} 个</span>}
                        {step.context_pack_ids.length > 0 && <span>上下文：{step.context_pack_ids.length} 个</span>}
                        {step.output_path && <span>输出：{step.output_path}</span>}
                        {step.error && <span className="workflow-step-error">错误：{step.error}</span>}
                      </div>
                      {typeof step.output.content === "string" && (
                        <pre className="workflow-step-output">{step.output.content.slice(0, 1200)}</pre>
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
