import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ForeshadowItem, StoryForeshadows } from "../types";

export function useForeshadows(projectPath: string | null) {
  const [foreshadows, setForeshadows] = useState<StoryForeshadows | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setForeshadows(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<StoryForeshadows>(`/story/foreshadows?project_path=${encodeURIComponent(projectPath)}`);
      setForeshadows(data);
      setError("");
    } catch {
      setError("无法加载伏笔");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const save = useCallback(async (items: ForeshadowItem[]) => {
    if (!projectPath) return null;
    setSaving(true);
    try {
      const data = await api.put<StoryForeshadows>("/story/foreshadows", {
        project_path: projectPath,
        items,
      });
      setForeshadows(data);
      setError("");
      return data;
    } catch {
      setError("无法保存伏笔");
      return null;
    } finally {
      setSaving(false);
    }
  }, [projectPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { foreshadows, loading, saving, error, refresh, save };
}
