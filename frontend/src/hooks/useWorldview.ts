import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StoryWorldview } from "../types";

export function useWorldview(projectPath: string | null) {
  const [worldview, setWorldview] = useState<StoryWorldview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setWorldview(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<StoryWorldview>(`/story/worldview?project_path=${encodeURIComponent(projectPath)}`);
      setWorldview(data);
      setError("");
    } catch {
      setError("无法加载世界观");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const saveDocument = useCallback(async (path: string, content: string) => {
    if (!projectPath) return;
    setSaving(true);
    try {
      await api.put("/story/worldview/document", {
        project_path: projectPath,
        path,
        content,
      });
      await refresh();
      setError("");
    } catch {
      setError("无法保存世界观文档");
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { worldview, loading, saving, error, refresh, saveDocument };
}
