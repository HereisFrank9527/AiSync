import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ToolDescriptor, ToolRunRecord } from "../types";

export function useTools(projectPath: string | null, presetId: string | null) {
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [runs, setRuns] = useState<ToolRunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ToolRunRecord | null>(null);
  const [running, setRunning] = useState(false);

  const projectQuery = useCallback(() => (
    projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : ""
  ), [projectPath]);

  const refreshRuns = useCallback(async () => {
    try {
      const list = await api.get<ToolRunRecord[]>(`/tools/runs${projectQuery()}`);
      setRuns(list);
    } catch {
      setRuns([]);
    }
  }, [projectQuery]);

  const refresh = useCallback(async () => {
    try {
      const list = await api.get<ToolDescriptor[]>(`/tools${projectQuery()}`);
      setTools(list);
      setError("");
      await refreshRuns();
    } catch {
      setError("无法加载工具列表");
    } finally {
      setLoading(false);
    }
  }, [projectQuery, refreshRuns]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const execute = useCallback(
    async (name: string, params: Record<string, unknown>) => {
      setRunning(true);
      setError("");
      try {
        const response = await api.post<ToolRunRecord>(`/tools/${name}/execute`, {
          project_path: projectPath,
          params,
        });
        setResult(response);
        await refreshRuns();
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : "工具执行失败";
        setError(message);
        throw err;
      } finally {
        setRunning(false);
      }
    },
    [projectPath, refreshRuns],
  );

  const invoke = useCallback(
    async (name: string, params: Record<string, unknown>, presetOverrideId?: string | null) => {
      setRunning(true);
      setError("");
      try {
        const response = await api.post<ToolRunRecord>(`/tools/${name}/invoke`, {
          project_path: projectPath,
          preset_id: presetOverrideId ?? presetId,
          params,
        });
        setResult(response);
        await refreshRuns();
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : "AI 执行失败";
        setError(message);
        throw err;
      } finally {
        setRunning(false);
      }
    },
    [projectPath, presetId, refreshRuns],
  );

  const clearResult = useCallback(() => {
    setResult(null);
    setError("");
  }, []);

  const updateDefaultPreset = useCallback(
    async (name: string, defaultPresetId: string | null) => {
      await api.put<{ name: string; default_preset_id: string | null }>(`/tools/${name}/settings`, {
        project_path: projectPath,
        default_preset_id: defaultPresetId,
      });
      await refresh();
    },
    [projectPath, refresh],
  );

  return {
    tools,
    runs,
    loading,
    error,
    result,
    running,
    refresh,
    refreshRuns,
    execute,
    invoke,
    updateDefaultPreset,
    clearResult,
  };
}
