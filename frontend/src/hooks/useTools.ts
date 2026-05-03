import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ToolDescriptor, ToolResult } from "../types";

export function useTools(projectPath: string | null, presetId: string | null) {
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ToolResult | null>(null);
  const [running, setRunning] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await api.get<ToolDescriptor[]>("/tools");
      setTools(list);
      setError("");
    } catch {
      setError("无法加载工具列表");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const execute = useCallback(
    async (name: string, params: Record<string, unknown>) => {
      setRunning(true);
      setError("");
      try {
        const response = await api.post<ToolResult>(`/tools/${name}/execute`, {
          project_path: projectPath,
          params,
        });
        setResult(response);
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : "工具执行失败";
        setError(message);
        throw err;
      } finally {
        setRunning(false);
      }
    },
    [projectPath],
  );

  const invoke = useCallback(
    async (name: string, params: Record<string, unknown>) => {
      setRunning(true);
      setError("");
      try {
        const response = await api.post<ToolResult>(`/tools/${name}/invoke`, {
          project_path: projectPath,
          preset_id: presetId,
          params,
        });
        setResult(response);
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : "AI 执行失败";
        setError(message);
        throw err;
      } finally {
        setRunning(false);
      }
    },
    [projectPath, presetId],
  );

  return { tools, loading, error, result, running, refresh, execute, invoke };
}
