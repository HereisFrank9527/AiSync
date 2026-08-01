import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ProjectPromptPackSettings, PromptPack, PromptPackCreate, PromptPackExample, PromptPackUpdate } from "../types";

export function usePromptPacks(projectPath: string | null = null) {
  const [packs, setPacks] = useState<PromptPack[]>([]);
  const [projectSettings, setProjectSettings] = useState<ProjectPromptPackSettings>({ mode: "global", enabled_pack_ids: [] });
  const [examples, setExamples] = useState<PromptPackExample[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const nextPacks = await api.get<PromptPack[]>("/prompt-packs");
      const nextExamples = await api.get<PromptPackExample[]>("/prompt-packs/examples");
      setPacks(nextPacks);
      setExamples(nextExamples);
      if (projectPath) {
        const settings = await api.get<ProjectPromptPackSettings>(
          `/prompt-packs/project-settings?project_path=${encodeURIComponent(projectPath)}`,
        );
        const knownIds = new Set(nextPacks.map((pack) => pack.id));
        setProjectSettings({
          mode: settings.mode,
          enabled_pack_ids: settings.enabled_pack_ids.filter((id) => knownIds.has(id)),
        });
      } else {
        setProjectSettings({ mode: "global", enabled_pack_ids: [] });
      }
      setError("");
    } catch (error) {
      setError(error instanceof Error ? error.message : "无法加载提示词包");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(async (data: PromptPackCreate) => {
    const pack = await api.post<PromptPack>("/prompt-packs", data);
    await refresh();
    return pack;
  }, [refresh]);

  const update = useCallback(async (id: string, data: PromptPackUpdate) => {
    const pack = await api.put<PromptPack>(`/prompt-packs/${id}`, data);
    await refresh();
    return pack;
  }, [refresh]);

  const copy = useCallback(async (id: string, name?: string | null) => {
    const pack = await api.post<PromptPack>(`/prompt-packs/${id}/copy`, { name });
    await refresh();
    return pack;
  }, [refresh]);

  const createFromExample = useCallback(async (exampleId: string) => {
    const pack = await api.post<PromptPack>(`/prompt-packs/examples/${exampleId}`, {});
    await refresh();
    return pack;
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    await api.del(`/prompt-packs/${id}`);
    await refresh();
  }, [refresh]);

  const updateProjectSettings = useCallback(async (settings: ProjectPromptPackSettings) => {
    if (!projectPath) {
      setProjectSettings(settings);
      return settings;
    }
    const saved = await api.put<ProjectPromptPackSettings>("/prompt-packs/project-settings", {
      project_path: projectPath,
      ...settings,
    });
    setProjectSettings(saved);
    return saved;
  }, [projectPath]);

  return { packs, examples, projectSettings, loading, error, refresh, create, createFromExample, update, copy, remove, updateProjectSettings };
}
