import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ProjectInfo, ProjectOverview, ProjectOverviewUpdate } from "../types";

export function useProjectOverview(projectPath: string | null, onProjectNameChange?: (name: string) => void) {
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setOverview(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<ProjectOverview>(`/projects/overview?project_path=${encodeURIComponent(projectPath)}`);
      setOverview(data);
      onProjectNameChange?.(data.name);
      setError("");
    } catch {
      setError("无法加载基础信息");
    } finally {
      setLoading(false);
    }
  }, [onProjectNameChange, projectPath]);

  const save = useCallback(async (payload: ProjectOverviewUpdate) => {
    if (!projectPath) return null;
    setSaving(true);
    try {
      const data = await api.put<ProjectOverview>("/projects/overview", {
        project_path: projectPath,
        ...payload,
      });
      setOverview(data);
      onProjectNameChange?.(data.name);
      setError("");
      return data;
    } catch {
      setError("无法保存基础信息");
      return null;
    } finally {
      setSaving(false);
    }
  }, [onProjectNameChange, projectPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { overview, loading, saving, error, refresh, save };
}

export function withProjectName(project: ProjectInfo, name: string): ProjectInfo {
  return { ...project, name };
}
