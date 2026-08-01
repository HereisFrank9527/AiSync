import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StoryCharacter, StoryCharacters, StoryCharacterUpdate } from "../types";

export function useCharacters(projectPath: string | null) {
  const [characters, setCharacters] = useState<StoryCharacters | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setCharacters(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<StoryCharacters>(`/story/characters?project_path=${encodeURIComponent(projectPath)}`);
      setCharacters(data);
      setError("");
    } catch {
      setError("无法加载角色");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const archive = useCallback(async (slug: string, reason = "") => {
    if (!projectPath) return null;
    const result = await api.post<{ slug: string; status: string; archive_path: string }>("/story/characters/archive", {
      project_path: projectPath,
      slug,
      reason,
    });
    await refresh();
    return result;
  }, [projectPath, refresh]);

  const save = useCallback(async (character: StoryCharacterUpdate) => {
    if (!projectPath) return null;
    setSaving(true);
    try {
      const result = await api.put<StoryCharacter>("/story/characters", {
        project_path: projectPath,
        ...character,
      });
      await refresh();
      setError("");
      return result;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "无法保存角色";
      setError(message);
      throw requestError;
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  const restore = useCallback(async (archiveId: string) => {
    if (!projectPath) return null;
    setSaving(true);
    try {
      const result = await api.post<{ slug: string; status: string }>("/story/characters/restore", {
        project_path: projectPath,
        archive_id: archiveId,
      });
      await refresh();
      setError("");
      return result;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "无法恢复角色";
      setError(message);
      throw requestError;
    } finally {
      setSaving(false);
    }
  }, [projectPath, refresh]);

  return { characters, loading, saving, error, refresh, save, archive, restore };
}
