import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { LLMParams, ModelListResponse, Preset, PresetCopy, PresetCreate, PresetUpdate } from "../types";

const BUILTIN_IDS = new Set(["default"]);
const STORAGE_KEY = "aisync:active_preset_id";

export function usePresets() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [activeId, setActiveIdRaw] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? "default",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const setActiveId = useCallback((id: string) => {
    setActiveIdRaw(id);
    localStorage.setItem(STORAGE_KEY, id);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const list = await api.get<Preset[]>("/presets");
      setPresets(list);
      setError("");
    } catch {
      setError("无法加载预设列表");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const activePreset =
    presets.find((p) => p.id === activeId) ?? presets[0] ?? null;

  const create = useCallback(
    async (data: PresetCreate) => {
      const created = await api.post<Preset>("/presets", data);
      await refresh();
      setActiveId(created.id);
      return created;
    },
    [refresh, setActiveId],
  );

  const update = useCallback(
    async (id: string, data: PresetUpdate) => {
      const updated = await api.put<Preset>(`/presets/${id}`, data);
      await refresh();
      return updated;
    },
    [refresh],
  );

  const copy = useCallback(
    async (id: string, data: PresetCopy = {}) => {
      const created = await api.post<Preset>(`/presets/${id}/copy`, data);
      await refresh();
      setActiveId(created.id);
      return created;
    },
    [refresh, setActiveId],
  );

  const listModels = useCallback(async (llm: LLMParams) => {
    return api.post<ModelListResponse>("/presets/models", llm);
  }, []);

  const remove = useCallback(
    async (id: string) => {
      await api.del(`/presets/${id}`);
      if (activeId === id) setActiveId("default");
      await refresh();
    },
    [activeId, refresh, setActiveId],
  );

  const isBuiltin = (id: string) => BUILTIN_IDS.has(id);

  return {
    presets,
    activeId,
    activePreset,
    loading,
    error,
    setActiveId,
    create,
    copy,
    update,
    listModels,
    remove,
    refresh,
    isBuiltin,
  };
}
