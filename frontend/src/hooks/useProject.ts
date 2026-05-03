import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import type { ProjectInfo } from "../types";

const STORAGE_KEY = "aisync:project";

function nameFromPath(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? "未命名项目";
}

export function useProject() {
  const [project, setProject] = useState<ProjectInfo | null>(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) as ProjectInfo : null;
  });

  useEffect(() => {
    if (project) localStorage.setItem(STORAGE_KEY, JSON.stringify(project));
  }, [project]);

  const selectFolder = useCallback(async () => {
    const selected = await open({ directory: true, multiple: false });
    if (typeof selected !== "string") return null;
    const next = { path: selected, name: nameFromPath(selected) };
    setProject(next);
    return next;
  }, []);

  return { project, setProject, selectFolder };
}
