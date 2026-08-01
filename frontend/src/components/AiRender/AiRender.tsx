import type { AgentEvent, ToolResult } from "../../types";
import { rendererFor } from "./rendererRegistry";
import type { AiRenderProps, UiHint } from "./types";
import "./AiRender.css";

function hintType(uiHint: UiHint) {
  const type = uiHint?.type;
  return typeof type === "string" ? type : "";
}

function stringify(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function MetadataView({ metadata }: { metadata?: Record<string, unknown> }) {
  const entries = Object.entries(metadata ?? {});
  if (!entries.length) return null;
  return (
    <dl className="ai-render-metadata">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{stringify(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function AiRender({ content, uiHint, metadata, compact, onWorkspaceChanged }: AiRenderProps) {
  const type = hintType(uiHint);
  const Renderer = rendererFor(type);
  const rendererOwnsMetadata = type === "list:issues";

  return (
    <div className={`ai-render${compact ? " ai-render--compact" : ""}`}>
      {type && !rendererOwnsMetadata && (
        <header className="ai-render-header">
          <span>{type}</span>
        </header>
      )}
      {!rendererOwnsMetadata && <MetadataView metadata={metadata} />}
      {Renderer ? (
        <Renderer
          content={content}
          uiHint={uiHint}
          metadata={metadata}
          compact={compact}
          onWorkspaceChanged={onWorkspaceChanged}
        />
      ) : uiHint ? (
        <pre className="ai-render-json">{JSON.stringify(uiHint, null, 2)}</pre>
      ) : content ? (
        <pre className="ai-render-json">{content}</pre>
      ) : null}
    </div>
  );
}

export function toolResultToRender(result: ToolResult): AiRenderProps {
  return {
    content: result.content,
    uiHint: result.ui_hint,
    metadata: result.metadata,
  };
}

export function eventToRender(event: AgentEvent): AiRenderProps {
  const uiType = hintType(event.ui_hint);
  return {
    content: event.content,
    uiHint: event.ui_hint,
    metadata: uiType === "list:issues" ? event.metadata : undefined,
  };
}
