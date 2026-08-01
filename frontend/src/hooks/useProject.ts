import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ProjectInfo } from "../types";

const STORAGE_KEY = "aisync:project";

function nameFromPath(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? "未命名项目";
}

export function useProject() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) as ProjectInfo : null;
  });

  useEffect(() => {
    if (project) localStorage.setItem(STORAGE_KEY, JSON.stringify(project));
  }, [project]);

  const refreshProjects = useCallback(async () => {
    setLoadingProjects(true);
    setProjectError(null);
    try {
      const items = await api.get<ProjectInfo[]>("/projects");
      setProjects(items);
      if (!project && items.length > 0) setProject(items[0]);
      return items;
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "加载项目失败");
      return [];
    } finally {
      setLoadingProjects(false);
    }
  }, [project]);

  useEffect(() => {
    void refreshProjects();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setProjectPath = useCallback((path: string) => {
    const trimmed = path.trim();
    if (!trimmed) return null;
    const next = { path: trimmed, name: nameFromPath(trimmed) };
    setProject(next);
    return next;
  }, []);

  const selectFolder = useCallback(async () => {
    const value = window.prompt("输入后端所在电脑上的项目文件夹绝对路径", project?.path ?? "");
    return value === null ? null : setProjectPath(value);
  }, [project?.path, setProjectPath]);

  const createProject = useCallback(async () => {
    const name = window.prompt("新建项目名称", "未命名项目");
    if (name === null) return null;
    const trimmed = name.trim();
    if (!trimmed) return null;
    const next = await api.post<ProjectInfo>("/projects", { name: trimmed });
    setProject(next);
    await refreshProjects();
    return next;
  }, [refreshProjects]);

  const importProject = useCallback(async (file: File) => {
    const imported = await api.uploadBytes<ProjectInfo>(
      `/projects/import?name=${encodeURIComponent(file.name.replace(/\.aisync\.zip$|\.zip$/i, ""))}`,
      file,
      "application/zip",
    );
    setProject(imported);
    await refreshProjects();
    return imported;
  }, [refreshProjects]);

  const exportProject = useCallback(async () => {
    if (!project?.path) return;
    const blob = await api.blob(`/projects/export?project_path=${encodeURIComponent(project.path)}`);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${project.name || "aisync-project"}.aisync.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [project?.name, project?.path]);

  const renameProject = useCallback(async () => {
    if (!project?.path) return null;
    const name = window.prompt("重命名项目", project.name);
    if (name === null) return null;
    const trimmed = name.trim();
    if (!trimmed) return null;
    const renamed = await api.put<ProjectInfo>("/projects/name", {
      project_path: project.path,
      name: trimmed,
    });
    setProject(renamed);
    await refreshProjects();
    return renamed;
  }, [project?.name, project?.path, refreshProjects]);

  const deleteProject = useCallback(async () => {
    if (!project?.path) return;
    const inLibrary = projects.some((item) => item.path === project.path);
    if (!inLibrary) {
      window.alert("当前项目不是项目库内项目，不能从这里删除。");
      return;
    }
    if (!window.confirm(`确定删除项目库中的项目？\n${project.name}\n\n建议先导出备份。`)) return;
    await api.del(`/projects?project_path=${encodeURIComponent(project.path)}`);
    const items = await refreshProjects();
    setProject(items[0] ?? null);
    if (items.length === 0) localStorage.removeItem(STORAGE_KEY);
  }, [project?.name, project?.path, projects, refreshProjects]);

  return {
    project,
    projects,
    loadingProjects,
    projectError,
    setProject,
    selectFolder,
    setProjectPath,
    createProject,
    importProject,
    exportProject,
    renameProject,
    deleteProject,
    refreshProjects,
  };
}
