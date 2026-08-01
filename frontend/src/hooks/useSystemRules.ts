import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ProjectSystemRules } from "../types";

const EMPTY_SYSTEM_RULES: ProjectSystemRules = {
  mode: "default",
  content: "",
  default_content: "",
  updated_at: null,
};

export function useSystemRules(projectPath: string | null = null) {
  const [settings, setSettings] = useState<ProjectSystemRules>(EMPTY_SYSTEM_RULES);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    if (!projectPath) {
      setSettings(EMPTY_SYSTEM_RULES);
      setError("");
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const next = await api.get<ProjectSystemRules>(
        `/system-rules?project_path=${encodeURIComponent(projectPath)}`,
      );
      if (version !== requestVersion.current) return;
      setSettings(next);
      setError("");
    } catch (error) {
      if (version !== requestVersion.current) return;
      setError(error instanceof Error ? error.message : "无法加载 AGENT.md");
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const update = useCallback(async (next: Pick<ProjectSystemRules, "mode" | "content">) => {
    if (!projectPath) {
      const local = { ...settings, ...next };
      setSettings(local);
      return local;
    }
    const version = ++requestVersion.current;
    setLoading(true);
    try {
      const saved = await api.put<ProjectSystemRules>("/system-rules", {
        project_path: projectPath,
        mode: next.mode,
        content: next.content,
      });
      if (version === requestVersion.current) {
        setSettings(saved);
        setError("");
      }
      return saved;
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [projectPath, settings]);

  return { settings, loading, error, refresh, update };
}
