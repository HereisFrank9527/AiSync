import { useEffect, useMemo, useState } from "react";
import type { FileNode } from "../../hooks/useFileTree";
import "./FileTree.css";

interface FileTreeProps {
  tree: FileNode[];
  activePath: string | null;
  onOpenFile: (path: string) => void;
}

function TreeNode({
  node,
  activePath,
  onOpenFile,
}: {
  node: FileNode;
  activePath: string | null;
  onOpenFile: (path: string) => void;
}) {
  const containsActivePath = useMemo(() => {
    if (!activePath) return false;
    return activePath === node.path || activePath.startsWith(`${node.path}/`);
  }, [activePath, node.path]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (containsActivePath) setExpanded(true);
  }, [containsActivePath]);

  if (node.isDir) {
    return (
      <div className="file-tree-dir">
        <button
          className="file-tree-dir-toggle"
          onClick={() => setExpanded((v) => !v)}
          title={node.path}
        >
          <span className={`file-tree-arrow${expanded ? " open" : ""}`} />
          <span className="file-tree-dir-name">{node.name}</span>
        </button>
        {expanded && node.children.length > 0 && (
          <div className="file-tree-dir-children">
            {node.children.map((child) => (
              <TreeNode key={child.path} node={child} activePath={activePath} onOpenFile={onOpenFile} />
            ))}
          </div>
        )}
        {expanded && node.children.length === 0 && (
          <div className="file-tree-empty-dir">空目录</div>
        )}
      </div>
    );
  }

  const editable = node.path.endsWith(".md");
  return (
    <button
      className={`file-tree-item${activePath === node.path ? " active" : ""}`}
      disabled={!editable}
      onClick={() => editable && onOpenFile(node.path)}
      title={node.path}
    >
      <span className="file-tree-name">{node.name}</span>
    </button>
  );
}

export default function FileTree({ tree, activePath, onOpenFile }: FileTreeProps) {
  if (tree.length === 0) {
    return <div className="file-tree-empty">暂无文件</div>;
  }

  return (
    <div className="file-tree">
      {tree.map((node) => (
        <TreeNode key={node.path} node={node} activePath={activePath} onOpenFile={onOpenFile} />
      ))}
    </div>
  );
}
