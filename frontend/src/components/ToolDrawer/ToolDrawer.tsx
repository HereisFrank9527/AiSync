import { lazy, Suspense } from "react";
import Drawer from "../common/Drawer";
import SchemaForm from "../SchemaForm";
import type { ToolDescriptor, ToolResult } from "../../types";
import "./ToolDrawer.css";

const MarkdownEditor = lazy(() => import("../MarkdownEditor"));

interface ToolDrawerProps {
  tool: ToolDescriptor | null;
  result: ToolResult | null;
  error: string;
  running: boolean;
  onClose: () => void;
  onExecute: (name: string, params: Record<string, unknown>) => void;
  onInvoke: (name: string, params: Record<string, unknown>) => void;
}

export default function ToolDrawer({
  tool,
  result,
  error,
  running,
  onClose,
  onExecute,
  onInvoke,
}: ToolDrawerProps) {
  return (
    <Drawer open={Boolean(tool)} title={tool?.name ?? "工具"} onClose={onClose}>
      {tool && (
        <div className="tool-drawer">
          <p className="tool-description">{tool.description}</p>
          {tool.ui_schema ? (
            <SchemaForm
              schema={tool.ui_schema}
              disabled={running}
              submitLabel="直接执行"
              secondaryLabel="AI 生成"
              onSubmit={(params) => onExecute(tool.name, params)}
              onSecondarySubmit={(params) => onInvoke(tool.name, params)}
            />
          ) : (
            <p className="tool-muted">这个工具暂未提供表单配置。</p>
          )}

          {error && <div className="tool-error">{error}</div>}
          {result && (
            <section className="tool-result">
              <h3>结果</h3>
              {result.ui_hint?.type === "stream:editor" ? (
                <div className="tool-result-editor">
                  <Suspense fallback={<p>加载编辑器…</p>}>
                    <MarkdownEditor
                      value={String((result.ui_hint.data as Record<string, unknown>)?.content ?? result.content)}
                      readonly
                    />
                  </Suspense>
                </div>
              ) : (
                <pre>{result.content}</pre>
              )}
            </section>
          )}
        </div>
      )}
    </Drawer>
  );
}
