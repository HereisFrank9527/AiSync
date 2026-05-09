import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { VectorIndexStatus, VectorSearchResult } from "../types";

export function useVectorIndex(projectPath: string | null) {
  const [status, setStatus] = useState<VectorIndexStatus | null>(null);
  const [results, setResults] = useState<VectorSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setStatus(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<VectorIndexStatus>(`/vector/status?project_path=${encodeURIComponent(projectPath)}`);
      setStatus(data);
      setError("");
    } catch {
      setError("无法加载索引状态");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const rebuild = useCallback(async () => {
    if (!projectPath) return;
    setRebuilding(true);
    try {
      await api.post(`/vector/rebuild?project_path=${encodeURIComponent(projectPath)}`, {});
      await refresh();
      setError("");
    } catch {
      setError("无法重建索引");
    } finally {
      setRebuilding(false);
    }
  }, [projectPath, refresh]);

  const search = useCallback(async (query: string, collections: string[], topK: number) => {
    if (!projectPath || !query.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const data = await api.post<{ items: VectorSearchResult[] }>("/vector/search", {
        project_path: projectPath,
        query,
        collections: collections.length ? collections : null,
        top_k: topK,
      });
      setResults(data.items);
      setError("");
    } catch {
      setError("无法检索索引");
    } finally {
      setSearching(false);
    }
  }, [projectPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { status, results, loading, rebuilding, searching, error, refresh, rebuild, search };
}
