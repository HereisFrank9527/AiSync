import { useMemo, useRef, useEffect, useLayoutEffect, useState, type KeyboardEvent } from "react";
import type { AgentEvent, ToolDescriptor } from "../../types";
import { AiRender, eventToRender } from "../AiRender";
import MarkdownView from "../MarkdownView";
import "./ChatPanel.css";

interface ChatPanelProps {
  events: AgentEvent[];
  historyVersion: number;
  connected: boolean;
  tools: ToolDescriptor[];
  onSend: (content: string, enabledTools?: string[] | null) => void;
  onInterrupt: () => void;
  input: string;
  onInputChange: (value: string) => void;
  showConversations?: boolean;
  onToggleConversations?: () => void;
}

const INITIAL_HISTORY_WINDOW = 120;
const HISTORY_PAGE_STEP = 80;
const BOTTOM_STICKY_DISTANCE = 96;

/** 合并连续的 stream 事件为单条消息，去除 stream_end */
function mergeStreamEvents(events: AgentEvent[]): AgentEvent[] {
  const merged: AgentEvent[] = [];
  for (const event of events) {
    if (event.type === "stream_end") continue;
    if (event.type === "agent_final") {
      const last = merged[merged.length - 1];
      if (last?.type === "stream") {
        last.type = "agent_final";
        last.content = event.content ?? last.content;
        last.conversation_id = event.conversation_id;
        continue;
      }
    }
    if (event.type === "stream") {
      const last = merged[merged.length - 1];
      if (last && last.type === "stream") {
        last.content = (last.content ?? "") + (event.content ?? "");
        continue;
      }
      merged.push({ ...event, sender: "agent" });
    } else {
      merged.push(event);
    }
  }
  return merged;
}

function memoryStatusText(event: AgentEvent) {
  const memory = event.memory ?? {};
  const parts = [`近期 ${memory.recent_messages ?? 0} 条`];
  parts.push(memory.summary ? "已注入摘要" : "无摘要");
  if (memory.summary_pending) parts.push("摘要后台更新中");
  const quality = memory.summary_quality;
  if (quality?.status === "weak" || quality?.status === "poor") {
    parts.push(`摘要${quality.score ?? 0}分`);
  } else if (quality?.status === "ok") {
    parts.push(`摘要${quality.score ?? 0}分`);
  }
  return parts.join(" · ");
}

function isSystemStatusEvent(event: AgentEvent) {
  return event.type === "memory_status" || event.type === "agent_limit_reached" || event.type === "agent_status";
}

function systemStatusText(event: AgentEvent) {
  if (event.type === "agent_limit_reached") return event.content ?? "Agent 已达到本轮迭代上限。";
  if (event.type === "agent_status") return event.content ?? "Agent 正在工作";
  return memoryStatusText(event);
}

function isErrorEvent(event: AgentEvent) {
  return event.type === "error";
}

function toolStatusText(event: AgentEvent) {
  const name = event.tool?.name ?? "unknown";
  if (event.type === "tool_call_start") return `调用工具 ${name}`;
  if (event.type === "tool_call_error") return `工具 ${name} 失败`;
  return `工具 ${name} 完成`;
}

function toolParamsText(params?: Record<string, unknown>) {
  const entries = Object.entries(params ?? {});
  if (!entries.length) return "";
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
}

function isToolStatusEvent(event: AgentEvent) {
  return event.type === "tool_call_start" || event.type === "tool_call_end" || event.type === "tool_call_error";
}

function agentActivityText(event: AgentEvent) {
  if (event.type === "agent_status") return event.content ?? "Agent 正在工作";
  if (event.type === "tool_call_start") return `调用工具 ${event.tool?.name ?? "unknown"}`;
  if (event.type === "tool_call_error") return event.content ?? `工具 ${event.tool?.name ?? "unknown"} 失败`;
  if (event.type === "tool_call_end") return `工具 ${event.tool?.name ?? "unknown"} 已完成`;
  if (event.type === "stream") return "正在生成回复";
  if (event.type === "agent_final") return "回复已完成";
  if (event.type === "agent_limit_reached") return event.content ?? "Agent 已暂停";
  if (event.type === "error") return event.content ?? "前台错误";
  return "";
}

function getWorkState(events: AgentEvent[], connected: boolean) {
  let pending = false;
  let label = connected ? "已连接" : "未连接";
  let kind: "idle" | "working" | "done" | "error" = "idle";

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "agent_final") {
      return { label: "回复已完成", kind: "done" as const };
    }
    if (event.type === "error" || event.type === "agent_limit_reached") {
      return { label: event.content ?? "前台错误", kind: "error" as const };
    }
    if (event.type === "stream" || event.type === "agent_status" || isToolStatusEvent(event)) {
      pending = true;
      label = agentActivityText(event) || "AI 正在工作";
      kind = "working";
    }
    if (event.sender === "user" && event.type === "user_message") {
      if (pending) return { label: label || "AI 正在工作", kind: "working" as const };
      return { label: "正在等待响应", kind: "working" as const };
    }
  }

  return { label, kind };
}

export default function ChatPanel({
  events,
  historyVersion,
  connected,
  tools,
  onSend,
  onInterrupt,
  input,
  onInputChange,
  showConversations,
  onToggleConversations,
}: ChatPanelProps) {
  const messagesRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const pendingScrollTargetRef = useRef<"top" | "bottom" | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [selectedTools, setSelectedTools] = useState<string[] | null>(null);
  const [visibleStart, setVisibleStart] = useState(0);
  const displayEvents = useMemo(() => mergeStreamEvents(events), [events]);
  const workState = useMemo(() => getWorkState(displayEvents, connected), [connected, displayEvents]);
  const visibleEvents = useMemo(() => displayEvents.slice(visibleStart), [displayEvents, visibleStart]);
  const allToolsEnabled = selectedTools === null;
  const enabledToolCount = allToolsEnabled ? tools.length : selectedTools.length;
  const canSend = Boolean(input.trim() && connected && enabledToolCount > 0);
  const toolSummary = allToolsEnabled
    ? "全部工具"
    : enabledToolCount === 0
      ? "未选择工具"
      : selectedTools.slice(0, 2).join(", ") + (enabledToolCount > 2 ? ` +${enabledToolCount - 2}` : "");

  useEffect(() => {
    const start = Math.max(0, displayEvents.length - INITIAL_HISTORY_WINDOW);
    stickToBottomRef.current = true;
    pendingScrollTargetRef.current = "bottom";
    setVisibleStart(start);
  }, [historyVersion]);

  useEffect(() => {
    setVisibleStart((current) => {
      const maxStart = Math.max(0, displayEvents.length - INITIAL_HISTORY_WINDOW);
      if (stickToBottomRef.current) {
        pendingScrollTargetRef.current = "bottom";
        return maxStart;
      }
      return Math.min(current, maxStart);
    });
  }, [displayEvents.length]);

  useLayoutEffect(() => {
    const target = pendingScrollTargetRef.current;
    if (!target) return;
    const container = messagesRef.current;
    if (!container) return;
    if (target === "top") {
      container.scrollTop = 0;
    } else {
      container.scrollTop = container.scrollHeight;
    }
    pendingScrollTargetRef.current = null;
  }, [visibleEvents.length, visibleStart]);

  useEffect(() => {
    setSelectedTools((current) => {
      if (current === null) return null;
      const available = new Set(tools.map((tool) => tool.name));
      return current.filter((name) => available.has(name));
    });
  }, [tools]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) {
        onSend(input, selectedTools);
        onInputChange("");
      }
    }
  };

  const handleSend = () => {
    if (canSend) {
      stickToBottomRef.current = true;
      pendingScrollTargetRef.current = "bottom";
      onSend(input, selectedTools);
      onInputChange("");
    }
  };

  const handleScroll = () => {
    const container = messagesRef.current;
    if (!container) return;
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    stickToBottomRef.current = distanceToBottom <= BOTTOM_STICKY_DISTANCE;
  };

  const loadEarlierMessages = () => {
    pendingScrollTargetRef.current = "top";
    stickToBottomRef.current = false;
    setVisibleStart((current) => Math.max(0, current - HISTORY_PAGE_STEP));
  };

  const toggleAllTools = (checked: boolean) => {
    setSelectedTools(checked ? null : tools.map((tool) => tool.name));
  };

  const toggleTool = (name: string, checked: boolean) => {
    setSelectedTools((current) => {
      const base = current ?? tools.map((tool) => tool.name);
      return checked ? Array.from(new Set([...base, name])) : base.filter((toolName) => toolName !== name);
    });
  };

  const selectEveryTool = () => {
    setSelectedTools(tools.map((tool) => tool.name));
  };

  const selectNoTools = () => {
    setSelectedTools([]);
  };

  const renderAgentContent = (event: AgentEvent, isStreaming: boolean, isLast: boolean) => {
    const hasAiRender = Boolean(event.ui_hint);
    if (hasAiRender) {
      return (
        <>
          {event.content && (
            <div className="chat-message-body">
              <MarkdownView content={event.content} />
            </div>
          )}
          <AiRender {...eventToRender(event)} compact />
        </>
      );
    }

    if (!event.content) return null;
    return (
      <div className={`chat-message-body${isStreaming && isLast ? " chat-message-body--streaming" : ""}`}>
        <MarkdownView content={event.content} />
        {isStreaming && isLast && <span className="chat-cursor" />}
      </div>
    );
  };

  return (
    <div className="chat-panel">
      <header className="chat-header">
        <div className="chat-header-left">
          {onToggleConversations && (
            <button className="btn-ghost" onClick={onToggleConversations}>
              {showConversations ? "隐藏历史" : "历史"}
            </button>
          )}
          <h2>对话</h2>
        </div>
        <div className="chat-header-actions">
          <div
            className={`chat-work-indicator is-${workState.kind}`}
            title={workState.label}
            aria-label={workState.label}
          >
            <span className="chat-work-indicator-icon" aria-hidden="true" />
            <span className="chat-work-indicator-text">{workState.label}</span>
          </div>
          <div className="chat-tool-picker">
            <button className="btn-secondary" onClick={() => setToolsOpen((value) => !value)}>
              工具 {enabledToolCount}/{tools.length}
            </button>
            {toolsOpen && (
              <div className="chat-tool-menu">
                <div className="chat-tool-summary" title={toolSummary}>
                  <span>{toolSummary}</span>
                </div>
                <label className="chat-tool-all">
                  <input type="checkbox" checked={allToolsEnabled} onChange={(event) => toggleAllTools(event.target.checked)} />
                  <span>全部工具</span>
                </label>
                {!allToolsEnabled && (
                  <div className="chat-tool-bulk">
                    <button className="btn-ghost" onClick={selectEveryTool}>全选</button>
                    <button className="btn-ghost" onClick={selectNoTools}>全不选</button>
                    <button className="btn-ghost" onClick={() => setSelectedTools(null)}>恢复默认</button>
                  </div>
                )}
                <div className="chat-tool-list">
                  {tools.map((tool) => (
                    <label key={tool.name} className="chat-tool-option">
                      <input
                        type="checkbox"
                        checked={allToolsEnabled || selectedTools.includes(tool.name)}
                        disabled={allToolsEnabled}
                        onChange={(event) => toggleTool(tool.name, event.target.checked)}
                      />
                      <span>
                        <strong>{tool.name}</strong>
                        <em>{tool.description}</em>
                      </span>
                    </label>
                  ))}
                  {tools.length === 0 && <p>工具列表尚未加载。</p>}
                </div>
              </div>
            )}
          </div>
          <button
            className="btn-ghost"
            onClick={onInterrupt}
            disabled={!connected}
          >
            中断
          </button>
        </div>
      </header>

      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {displayEvents.length === 0 && (
          <div className="chat-empty">发送消息开始对话</div>
        )}
        {visibleStart > 0 && (
          <div className="chat-history-loader">
            <button className="btn-ghost" onClick={loadEarlierMessages}>
              加载更早记录
            </button>
            <span>还有 {visibleStart} 条更早消息未渲染</span>
          </div>
        )}
        {visibleEvents.map((event, i) => {
          const isUser = event.sender === "user";
          const isSystemStatus = isSystemStatusEvent(event);
          const isError = isErrorEvent(event);
          const isToolStatus = isToolStatusEvent(event);
          const isStreaming = event.type === "stream";
          const isLast = i === visibleEvents.length - 1;
          if (isSystemStatus) {
            return (
              <div key={i} className="chat-message chat-message--system">
                <span>{systemStatusText(event)}</span>
              </div>
            );
          }
          if (isError) {
            return (
              <div key={i} className="chat-message chat-message--system is-error">
                <span>{event.content ?? "前台错误"}</span>
              </div>
            );
          }
          if (isToolStatus) {
            const paramsText = toolParamsText(event.tool?.params);
            return (
              <div key={i} className={`chat-message chat-message--tool ${event.type === "tool_call_error" ? "is-error" : ""}`}>
                <div>
                  <strong>{toolStatusText(event)}</strong>
                  {typeof event.tool?.duration_ms === "number" && <span>{event.tool.duration_ms}ms</span>}
                </div>
                {paramsText && <p>{paramsText}</p>}
                {event.tool?.error && <p>{event.tool.error}</p>}
              </div>
            );
          }
          return (
            <div key={i} className={`chat-message ${isUser ? "chat-message--user" : "chat-message--agent"}`}>
              {!isUser && event.type !== "stream" && (
                <div className="chat-message-type">{event.type}</div>
              )}
              {isUser && event.content && (
                <div className={`chat-message-body${isStreaming && isLast ? " chat-message-body--streaming" : ""}`}>
                  {event.content}
                  {isStreaming && isLast && <span className="chat-cursor" />}
                </div>
              )}
              {!isUser && renderAgentContent(event, isStreaming, isLast)}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
        {!allToolsEnabled && enabledToolCount === 0 && (
          <p className="chat-input-warning">至少选择一个工具，或恢复默认全部工具。</p>
        )}
        <div className="chat-input-row">
          <textarea
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            disabled={!connected}
          />
          <button
            className="btn-primary"
            onClick={handleSend}
            disabled={!canSend}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
