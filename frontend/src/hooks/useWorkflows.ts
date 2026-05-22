import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { WorkflowRunCreate, WorkflowRunRecord, WorkflowRunStatus } from "../types";

export function useWorkflows(projectPath: string | null) {
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [activeRun, setActiveRun] = useState<WorkflowRunRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
      setRuns(list);
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
    void refresh();
  }, [refresh]);

  const create = useCallback(async (data: WorkflowRunCreate) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows${projectQuery()}`, data);
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const updateStatus = useCallback(async (runId: string, status: WorkflowRunStatus) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.put<WorkflowRunRecord>(`/workflows/${runId}${projectQuery()}`, { status });
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const runNext = useCallback(async (runId: string) => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/run-next${projectQuery()}`, {});
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const confirm = useCallback(async (runId: string, note = "") => {
    if (!projectPath) throw new Error("请先选择项目");
    const run = await api.post<WorkflowRunRecord>(`/workflows/${runId}/confirm${projectQuery()}`, { note });
    setActiveRun(run);
    await refresh();
    return run;
  }, [projectPath, projectQuery, refresh]);

  const selectRun = useCallback((runId: string) => {
    setActiveRun(runs.find((run) => run.run_id === runId) ?? null);
  }, [runs]);

  return { runs, activeRun, loading, error, refresh, create, updateStatus, runNext, confirm, selectRun };
}
