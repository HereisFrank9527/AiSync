import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StoryWorldview, WorldviewDocument } from "../types";

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
    if (!projectPath) return null;
    setSaving(true);
    try {
      const result = await api.put<WorldviewDocument>("/story/worldview/document", {
        project_path: projectPath,
        path,
        content,
      });
      await refresh();
      setError("");
      return result;
    } catch {
      setError("无法保存世界观文档");
      return null;
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  const renameDocument = useCallback(async (oldPath: string, newPath: string) => {
    if (!projectPath) return null;
    setSaving(true);
    try {
      const result = await api.post<WorldviewDocument & { old_path: string }>("/story/worldview/document/rename", {
        project_path: projectPath,
        old_path: oldPath,
        new_path: newPath,
      });
      await refresh();
      setError("");
      return result;
    } catch {
      setError("无法重命名世界观文档");
      return null;
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  const deleteDocument = useCallback(async (path: string) => {
    if (!projectPath) return;
    setSaving(true);
    try {
      await api.post("/story/worldview/document/delete", {
        project_path: projectPath,
        path,
      });
      await refresh();
      setError("");
      return true;
    } catch {
      setError("无法删除世界观文档");
      return false;
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { worldview, loading, saving, error, refresh, saveDocument, renameDocument, deleteDocument };
}
