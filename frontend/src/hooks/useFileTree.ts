import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

export interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children: FileNode[];
  zone?: "formal" | "temp";
}

/** 将扁平的 path 列表转为树形结构，过滤 .aisync，目录在前文件在后 */
function buildTree(paths: string[]): FileNode[] {
  const root: FileNode = { name: "", path: "", isDir: true, children: [] };

  function zoneForPath(path: string): FileNode["zone"] {
    return path.split("/")[0] === "temp" ? "temp" : "formal";
  }

  function ensureDir(path: string) {
    const segments = path.replace(/\\/g, "/").split("/").filter(Boolean);
    let current = root;
    let accumulated = "";

    for (const seg of segments) {
      accumulated = accumulated ? `${accumulated}/${seg}` : seg;
      let node = current.children.find((c) => c.name === seg);
      if (!node) {
        node = {
          name: seg,
          path: accumulated,
          isDir: true,
          children: [],
          zone: zoneForPath(accumulated),
        };
        current.children.push(node);
      } else {
        node.isDir = true;
        node.zone = node.zone ?? zoneForPath(accumulated);
      }
      current = node;
    }
  }

  const normalizedPaths = paths.map((p) => p.replace(/\\/g, "/"));
  for (const dir of ["temp", "temp/inbox", "temp/drafts", "temp/exports", "temp/notes"]) {
    ensureDir(dir);
  }

  const filtered = normalizedPaths.filter((p) => {
    const seg = p.split("/");
    return seg[0] !== ".aisync" && seg[0] !== ".vectordb";
  }).filter((p) => {
    return p !== "temp/.aisync-temp.json";
  });

  for (const raw of filtered.sort()) {
    const segments = raw.split("/");
    let current = root;
    let accumulated = "";

    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      accumulated = accumulated ? `${accumulated}/${seg}` : seg;
      const isLast = i === segments.length - 1;

      let node = current.children.find((c) => c.name === seg);
      if (!node) {
        node = {
          name: seg,
          path: accumulated,
          isDir: !isLast,
          children: [],
          zone: zoneForPath(accumulated),
        };
        current.children.push(node);
      } else if (isLast) {
        node.isDir = false;
        node.zone = node.zone ?? zoneForPath(accumulated);
      }
      current = node;
    }
  }

  function sortChildren(nodes: FileNode[]) {
    nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) sortChildren(n.children);
  }
  sortChildren(root.children);

  return root.children;
}

export function useFileTree(projectPath: string | null) {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setTree([]);
      return;
    }
    setLoading(true);
    try {
      const response = await api.get<{ files: string[] }>(`/projects/files?project_path=${encodeURIComponent(projectPath)}`);
      setTree(buildTree(response.files));
      setError("");
    } catch {
      setError("无法加载文件列表");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { tree, loading, error, refresh };
}
