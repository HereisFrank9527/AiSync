import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ChapterBatchWorkflowCreate, WorkflowRunCreate, WorkflowRunRecord, WorkflowRunStatus, WorkflowStepRecord, WorkflowStepUpdate, WorkflowTemplate } from "../types";

export function useWorkflows(projectPath: string | null) {
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [activeRun, setActiveRun] = useState<WorkflowRunRecord | null>(null);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [executingRunId, setExecutingRunId] = useState<string | null>(null);
  const [continuousRunId, setContinuousRunId] = useState<string | null>(null);
  const stopContinuousRef = useRef(false);

  const projectQuery = useCallback(() => (
    projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : ""
  ), [projectPath]);

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setRuns([]);
      setActiveRun(null);
      return;
    }
    setLoading(true);
    try {
      const list = await api.get<WorkflowRunRecord[]>(`/workflows${projectQuery()}`);
      const nextTemplates = await api.get<WorkflowTemplate[]>("/workflows/templates");
      setRuns(list);
      setTemplates(nextTemplates);
      setActiveRun((current) => {
        if (!current) return list[0] ?? null;
        return list.find((run) => run.run_id === current.run_id) ?? list[0] ?? null;
      });
      setError("");
    } catch (error) {
      setError(error instanceof Error ? error.message : "无法加载工作流");
    } finally {
      setLoading(false);
    }
  }, [projectPath, projectQuery]);

  useEffect(() => {
    stopContinuousRef.current = true;
    void refresh();
  }, [refresh]);

  const applyRun = useCallback((run: WorkflowRunRecord) => {
    setActiveRun(run);
    setRuns((current) => {
      const next = current.filter((item) => item.run_id !== run.run_id);
      return [run, ...next];
    });
  }, []);

  const create = useCallback(async (data: WorkflowRunCreate) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows${projectQuery()}`, data);
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const createFromTemplate = useCallback(async (templateId: string, data: { title?: string; input_summary?: string } = {}) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/templates/${templateId}${projectQuery()}`, data);
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const createChapterBatch = useCallback(async (data: ChapterBatchWorkflowCreate) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/chapter-batches${projectQuery()}`, data);
    applyRun(run);
    return run;
  }, [applyRun, projectPath, projectQuery]);

  const updateStatus = useCallback(async (runId: string, status: WorkflowRunStatus) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.put<WorkflowRunRecord>(`/workflows/${runId}${projectQuery()}`, { status });
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const updateRun = useCallback(async (runId: string, data: Partial<Pick<WorkflowRunRecord, "title" | "input_summary" | "metadata">> & { status?: WorkflowRunStatus }) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.put<WorkflowRunRecord>(`/workflows/${runId}${projectQuery()}`, data);
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const runNext = useCallback(async (runId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    if (executingRunId) throw new Error("已有工作流步骤正在执行");
    setExecutingRunId(runId);
    try {
      const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/run-next${projectQuery()}`, {});
      applyRun(run);
      setError("");
      return run;
    } catch (error) {
      const message = error instanceof Error ? error.message : "工作流执行失败";
      setError(message);
      throw error;
    } finally {
      setExecutingRunId(null);
    }
  }, [applyRun, executingRunId, projectPath, projectQuery]);

  const runContinuous = useCallback(async (runId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    if (executingRunId) throw new Error("已有工作流步骤正在执行");
    stopContinuousRef.current = false;
    setExecutingRunId(runId);
    setContinuousRunId(runId);
    try {
      let run: WorkflowRunRecord | null = null;
      while (!stopContinuousRef.current) {
        const nextRun = await api.post<WorkflowRunRecord>(`/workflows/${runId}/run-next${projectQuery()}`, {});
        run = nextRun;
        applyRun(nextRun);
        const currentStep = nextRun.steps.find((step) => step.step_id === nextRun.current_step_id);
        if (
          ["completed", "failed", "paused", "cancelled"].includes(nextRun.status)
          || currentStep?.status === "waiting_user"
        ) {
          break;
        }
      }
      setError("");
      return run;
    } catch (error) {
      const message = error instanceof Error ? error.message : "连续执行失败";
      setError(message);
      throw error;
    } finally {
      setExecutingRunId(null);
      setContinuousRunId(null);
      await refresh();
    }
  }, [applyRun, executingRunId, projectPath, projectQuery, refresh]);

  const pause = useCallback(async (runId: string) => {
    stopContinuousRef.current = true;
    return updateStatus(runId, "paused");
  }, [updateStatus]);

  const confirm = useCallback(async (runId: string, note = "") => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/confirm${projectQuery()}`, { note });
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const updateStep = useCallback(async (runId: string, stepId: string, data: WorkflowStepUpdate) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.put<WorkflowRunRecord>(`/workflows/${runId}/steps/${stepId}${projectQuery()}`, data);
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const addStep = useCallback(async (runId: string, data: Partial<WorkflowStepRecord> & { name: string }) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/steps${projectQuery()}`, data);
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const deleteStep = useCallback(async (runId: string, stepId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    await api.del(`/workflows/${runId}/steps/${stepId}${projectQuery()}`);
    await refresh();
  }, [projectPath, projectQuery, refresh]);

  const resetStep = useCallback(async (runId: string, stepId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/steps/${stepId}/reset${projectQuery()}`, {});
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const skipStep = useCallback(async (runId: string, stepId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/steps/${stepId}/skip${projectQuery()}`, {});
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const remove = useCallback(async (runId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    await api.del(`/workflows/${runId}${projectQuery()}`);
    setActiveRun((current) => current?.run_id === runId ? null : current);
    await refresh();
  }, [projectPath, projectQuery, refresh]);

  const selectRun = useCallback((runId: string) => {
    setActiveRun(runs.find((run) => run.run_id === runId) ?? null);
  }, [runs]);

  return {
    runs,
    activeRun,
    templates,
    loading,
    error,
    refresh,
    create,
    createFromTemplate,
    createChapterBatch,
    updateStatus,
    updateRun,
    updateStep,
    addStep,
    deleteStep,
    resetStep,
    skipStep,
    remove,
    runNext,
    runContinuous,
    pause,
    executingRunId,
    continuousRunId,
    confirm,
    selectRun,
  };
}
