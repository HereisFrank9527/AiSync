import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { OutlineItem, StoryOutline } from "../types";

export function useOutline(projectPath: string | null) {
  const [outline, setOutline] = useState<StoryOutline | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setOutline(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<StoryOutline>(`/story/outline?project_path=${encodeURIComponent(projectPath)}`);
      setOutline(data);
      setError("");
    } catch {
      setError("无法加载大纲");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const save = useCallback(async (title: string, items: OutlineItem[]) => {
    if (!projectPath) return null;
    setLoading(true);
    try {
      const data = await api.put<StoryOutline>("/story/outline", {
        project_path: projectPath,
        title,
        items,
      });
      setOutline(data);
      setError("");
      return data;
    } catch {
      setError("无法保存大纲");
      return null;
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const importMarkdown = useCallback(async () => {
    if (!projectPath) return null;
    setLoading(true);
    try {
      const data = await api.post<StoryOutline>("/story/outline/import-markdown", {
        project_path: projectPath,
      });
      setOutline(data);
      setError("");
      return data;
    } catch {
      setError("无法导入 Markdown 大纲");
      return null;
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { outline, loading, error, refresh, save, importMarkdown };
}
