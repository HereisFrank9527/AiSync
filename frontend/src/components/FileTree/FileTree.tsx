import { useEffect, useMemo, useState } from "react";
import type { FileNode } from "../../hooks/useFileTree";
import "./FileTree.css";

interface FileTreeProps {
  tree: FileNode[];
  activePath: string | null;
  onOpenFile: (path: string) => void;
  onCreateTempFile?: (dirPath: string) => void;
  onDeleteDirectory?: (dirPath: string) => void;
  onRenameTempFile?: (path: string) => void;
  onDeleteTempFile?: (path: string) => void;
}

const TEMP_TEXT_EXTENSIONS = [".md", ".txt", ".json", ".yaml", ".yml", ".csv"];

function isEditableFile(node: FileNode) {
  if (node.path.endsWith(".md")) return true;
  return node.zone === "temp" && TEMP_TEXT_EXTENSIONS.some((ext) => node.path.toLowerCase().endsWith(ext));
}

function TreeNode({
  node,
  activePath,
  onOpenFile,
  onCreateTempFile,
  onDeleteDirectory,
  onRenameTempFile,
  onDeleteTempFile,
}: {
  node: FileNode;
  activePath: string | null;
  onOpenFile: (path: string) => void;
  onCreateTempFile?: (dirPath: string) => void;
  onDeleteDirectory?: (dirPath: string) => void;
  onRenameTempFile?: (path: string) => void;
  onDeleteTempFile?: (path: string) => void;
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
        <div className="file-tree-dir-header">
          <button
            className="file-tree-dir-toggle"
            onClick={() => setExpanded((v) => !v)}
            title={node.path}
          >
            <span className={`file-tree-arrow${expanded ? " open" : ""}`} />
            <span className="file-tree-dir-name">{node.name}</span>
            {node.path === "temp" && <span className="file-tree-zone-badge">自由区</span>}
          </button>
          <span className="file-tree-dir-actions">
            {node.zone === "temp" && (
              <button
                className="file-tree-action"
                onClick={() => onCreateTempFile?.(node.path)}
                title={`在 ${node.path} 新建文本文件`}
              >
                新建
              </button>
            )}
            {node.path !== "temp" && (
              <button
                className="file-tree-action file-tree-action--danger"
                onClick={() => onDeleteDirectory?.(node.path)}
                title={`删除 ${node.path} 下的文本文件`}
              >
                删目录
              </button>
            )}
          </span>
        </div>
        {expanded && node.children.length > 0 && (
          <div className="file-tree-dir-children">
            {node.children.map((child) => (
              <TreeNode
                key={child.path}
                node={child}
                activePath={activePath}
                onOpenFile={onOpenFile}
                onCreateTempFile={onCreateTempFile}
                onDeleteDirectory={onDeleteDirectory}
                onRenameTempFile={onRenameTempFile}
                onDeleteTempFile={onDeleteTempFile}
              />
            ))}
          </div>
        )}
        {expanded && node.children.length === 0 && (
          <div className="file-tree-empty-dir">空目录</div>
        )}
      </div>
    );
  }

  const editable = isEditableFile(node);
  return (
    <div className={`file-tree-row${activePath === node.path ? " active" : ""}`}>
      <button
        className="file-tree-item"
        disabled={!editable}
        onClick={() => editable && onOpenFile(node.path)}
        title={editable ? node.path : `${node.path} 暂不支持在编辑器中打开`}
      >
        <span className="file-tree-name">{node.name}</span>
        {node.zone === "temp" && <span className="file-tree-zone-dot" title="自由区文件" />}
      </button>
      {node.zone === "temp" && (
        <span className="file-tree-inline-actions">
          <button onClick={() => onRenameTempFile?.(node.path)} title="重命名">改名</button>
          <button onClick={() => onDeleteTempFile?.(node.path)} title="删除">删除</button>
        </span>
      )}
    </div>
  );
}

export default function FileTree({
  tree,
  activePath,
  onOpenFile,
  onCreateTempFile,
  onDeleteDirectory,
  onRenameTempFile,
  onDeleteTempFile,
}: FileTreeProps) {
  if (tree.length === 0) {
    return <div className="file-tree-empty">暂无文件</div>;
  }

  return (
    <div className="file-tree">
      {tree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          activePath={activePath}
          onOpenFile={onOpenFile}
          onCreateTempFile={onCreateTempFile}
          onDeleteDirectory={onDeleteDirectory}
          onRenameTempFile={onRenameTempFile}
          onDeleteTempFile={onDeleteTempFile}
        />
      ))}
    </div>
  );
}
