import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { StoryCharacters } from "../types";

export function useCharacters(projectPath: string | null) {
  const [characters, setCharacters] = useState<StoryCharacters | null>(null);
  const [loading, setLoading] = useState(false);
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

  return { characters, loading, error, refresh };
}
