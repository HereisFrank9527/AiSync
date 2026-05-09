import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StoryChapterMetadataUpdate, StoryChapters } from "../types";

export function useChapters(projectPath: string | null) {
  const [chapters, setChapters] = useState<StoryChapters | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setChapters(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<StoryChapters>(`/story/chapters?project_path=${encodeURIComponent(projectPath)}`);
      setChapters(data);
      setError("");
    } catch {
      setError("无法加载章节");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const saveDocument = useCallback(async (path: string, content: string) => {
    if (!projectPath) return;
    setSaving(true);
    try {
      await api.put("/story/chapters/document", {
        project_path: projectPath,
        path,
        content,
      });
      await refresh();
      setError("");
    } catch {
      setError("无法保存章节");
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  const saveMetadata = useCallback(async (path: string, metadata: StoryChapterMetadataUpdate) => {
    if (!projectPath) return;
    setSaving(true);
    try {
      await api.put("/story/chapters/metadata", {
        project_path: projectPath,
        path,
        ...metadata,
      });
      await refresh();
      setError("");
    } catch {
      setError("无法保存章节元数据");
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { chapters, loading, saving, error, refresh, saveDocument, saveMetadata };
}
