import { useMemo, useRef, useEffect, useLayoutEffect, useState, type KeyboardEvent } from "react";
import type { AgentEvent, ConversationStatus, ToolDescriptor } from "../../types";
import { AiRender, eventToRender } from "../AiRender";
import MarkdownView from "../MarkdownView";
import "./ChatPanel.css";

interface ChatPanelProps {
  events: AgentEvent[];
  historyVersion: number;
  connected: boolean;
  conversationStatus?: ConversationStatus | null;
  conversationLastError?: string | null;
  tools: ToolDescriptor[];
  onSend: (
    content: string,
    enabledTools?: string[] | null,
    options?: { modelContent?: string; metadata?: Record<string, unknown> },
  ) => void;
  onInterrupt: () => void;
  input: string;
  onInputChange: (value: string) => void;
  showConversations?: boolean;
  onToggleConversations?: () => void;
}

const INITIAL_HISTORY_WINDOW = 120;
const HISTORY_PAGE_STEP = 80;
const BOTTOM_STICKY_DISTANCE = 96;
const REFERENCE_CONTEXT_HEADER = "[引用上下文，供本轮回复参考]";
const REFERENCE_CONTEXT_FOOTER = "[/引用上下文]";

/** 合并流式事件，并把同一轮的 stream + agent_final 折叠成一条消息。 */
function mergeStreamEvents(events: AgentEvent[]): AgentEvent[] {
  const merged: AgentEvent[] = [];
  for (const event of events) {
    if (event.type === "stream_end") continue;
    if (event.type === "agent_final") {
      const lastUserIndex = findLastIndex(merged, (item) => item.sender === "user" && item.type === "user_message");
      const duplicateFinalIndex = findLastIndex(
        merged,
        (item, index) =>
          index > lastUserIndex &&
          item.type === "agent_final" &&
          normalizeContent(item.content) === normalizeContent(event.content),
      );
      if (duplicateFinalIndex >= 0) continue;

      const streamIndex = findLastIndex(
        merged,
        (item, index) => index > lastUserIndex && item.type === "stream" && item.sender !== "user",
      );
      if (streamIndex >= 0) {
        merged[streamIndex] = {
          ...merged[streamIndex],
          ...event,
          type: "agent_final",
          sender: "agent",
          content: event.content ?? merged[streamIndex].content,
        };
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

function findLastIndex<T>(items: T[], predicate: (item: T, index: number) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index], index)) return index;
  }
  return -1;
}

function normalizeContent(content?: string) {
  return (content ?? "").replace(/\s+/g, " ").trim();
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

function isTaskListEvent(event: AgentEvent) {
  return event.type === "agent_task_list";
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
    const phase = typeof event.metadata?.phase === "string" ? event.metadata.phase : "";
    if (event.type === "agent_final") {
      return { label: "回复已完成", kind: "done" as const };
    }
    if (event.type === "error" || event.type === "agent_limit_reached") {
      return { label: event.content ?? "前台错误", kind: "error" as const };
    }
    if (event.type === "agent_status" && (phase === "done" || phase === "interrupted" || phase === "interrupt_requested")) {
      return { label: event.content ?? "Agent 已停止", kind: "done" as const };
    }
    if (event.type === "agent_status" && phase === "error") {
      return { label: event.content ?? "Agent 出错", kind: "error" as const };
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

function conversationStatusToWorkState(
  status: ConversationStatus | null | undefined,
  lastError: string | null | undefined,
  connected: boolean,
) {
  if (status === "running") return { label: "上次响应未正常结束", kind: "error" as const };
  if (status === "failed") return { label: lastError ? `上次失败：${lastError}` : "上次响应失败", kind: "error" as const };
  if (status === "interrupted") return { label: "上次响应已中断", kind: "done" as const };
  if (status === "completed") return { label: "上次回复已完成", kind: "done" as const };
  return { label: connected ? "已连接" : "未连接", kind: "idle" as const };
}

function isSelectableMessage(event: AgentEvent) {
  if (!event.content?.trim()) return false;
  if (event.sender === "user" && event.type === "user_message") return true;
  return event.type === "agent_final" || event.type === "stream";
}

function messageRoleLabel(event: AgentEvent) {
  return event.sender === "user" ? "用户" : "AI";
}

function formatSelectedMessages(events: AgentEvent[]) {
  return events
    .filter(isSelectableMessage)
    .map((event) => `${messageRoleLabel(event)}：\n${event.content?.trim() ?? ""}`)
    .join("\n\n---\n\n");
}

interface QuoteReference {
  role: string;
  content: string;
  lineCount: number;
}

interface ReferencedUserContent {
  content: string;
  referenceLines: number;
  referenceCount: number;
}

function quoteReferencesFromEvents(events: AgentEvent[]) {
  return events
    .filter(isSelectableMessage)
    .map((event) => {
      const content = (event.content ?? "").trim();
      return {
        role: messageRoleLabel(event),
        content,
        lineCount: countContentLines(content),
      };
    })
    .filter((reference) => reference.content);
}

function countContentLines(content: string) {
  return Math.max(1, content.split(/\r?\n/).filter((line) => line.trim()).length);
}

function summarizeQuoteReferences(references: QuoteReference[]) {
  const lineCount = references.reduce((total, reference) => total + reference.lineCount, 0);
  const messageCount = references.length;
  return {
    lineCount,
    messageCount,
    label: messageCount > 1 ? `引用 ${messageCount} 条消息 · ${lineCount} 行文字` : `引用 ${lineCount} 行文字`,
  };
}

function buildModelMessageWithReferences(content: string, references: QuoteReference[]) {
  const message = content.trim();
  if (!references.length) return message;
  const referenceBlock = references
    .map((reference, index) => `[${index + 1}] ${reference.role}（${reference.lineCount}行）\n${reference.content}`)
    .join("\n\n");
  return `${message}\n\n${REFERENCE_CONTEXT_HEADER}\n${referenceBlock}\n${REFERENCE_CONTEXT_FOOTER}`;
}

function metadataReferencedUserContent(content: string, metadata?: Record<string, unknown>): ReferencedUserContent | null {
  const referenceLines = Number(metadata?.quote_reference_lines ?? 0);
  const referenceCount = Number(metadata?.quote_reference_count ?? 0);
  if (referenceLines <= 0) return null;
  return { content, referenceLines, referenceCount };
}

function markerReferencedUserContent(content?: string): ReferencedUserContent {
  const raw = content ?? "";
  const headerIndex = raw.lastIndexOf(REFERENCE_CONTEXT_HEADER);
  if (headerIndex < 0) {
    return { content: raw, referenceLines: 0, referenceCount: 0 };
  }
  const footerIndex = raw.indexOf(REFERENCE_CONTEXT_FOOTER, headerIndex + REFERENCE_CONTEXT_HEADER.length);
  const referenceBlock = raw
    .slice(headerIndex + REFERENCE_CONTEXT_HEADER.length, footerIndex >= 0 ? footerIndex : raw.length)
    .trim();
  const referenceLines = [...referenceBlock.matchAll(/（(\d+)行）/g)]
    .reduce((total, match) => total + Number(match[1] || 0), 0);
  const referenceCount = (referenceBlock.match(/^\[\d+\]/gm) ?? []).length;
  return {
    content: raw.slice(0, headerIndex).trimEnd(),
    referenceLines: referenceLines || countContentLines(referenceBlock),
    referenceCount,
  };
}

function displayReferencedUserContent(content?: string, metadata?: Record<string, unknown>): ReferencedUserContent {
  return metadataReferencedUserContent(content ?? "", metadata) ?? markerReferencedUserContent(content);
}

interface ChoiceOption {
  label: string;
  value: string;
}

interface AgentTaskItem {
  label: string;
  status: "pending" | "active" | "done" | "error";
}

interface AgentTaskList {
  tasks: AgentTaskItem[];
  activeLabel: string;
  done: boolean;
}

function parseAgentTaskList(event?: AgentEvent): AgentTaskList | null {
  const rawTasks = event?.metadata?.tasks;
  if (!Array.isArray(rawTasks)) return null;
  const tasks = rawTasks
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const label = typeof record.label === "string" ? record.label : "";
      const rawStatus = typeof record.status === "string" ? record.status : "pending";
      const status = ["pending", "active", "done", "error"].includes(rawStatus)
        ? rawStatus as AgentTaskItem["status"]
        : "pending";
      return label ? { label, status } : null;
    })
    .filter((item): item is AgentTaskItem => Boolean(item));
  if (!tasks.length) return null;
  const active = tasks.find((task) => task.status === "active");
  return {
    tasks,
    activeLabel: active?.label ?? (tasks.every((task) => task.status === "done") ? "任务已完成" : tasks[0].label),
    done: tasks.every((task) => task.status === "done"),
  };
}

function extractChoiceOptions(content?: string): ChoiceOption[] {
  if (!content) return [];
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const options: ChoiceOption[] = [];
  let collecting = false;
  let headingSeen = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (collecting && options.length > 0) break;
      continue;
    }
    if (/(可选方案|下一步选项|选择一个|你可以选|请选择|几个方案|方案如下)/.test(line)) {
      headingSeen = true;
      collecting = true;
      continue;
    }

    const item = /^(?:[-*]|\d+[.)、]|[A-Ha-h][.)、]|[一二三四五六七八九十]+[.)、])\s*(.+)$/.exec(line);
    if (item && collecting) {
      const value = cleanChoiceText(item[1]);
      if (value) options.push({ label: value, value });
      if (options.length >= 6) break;
      continue;
    }

    if (collecting && options.length > 0) break;
  }

  if (!headingSeen || options.length < 2) return [];
  return options;
}

function cleanChoiceText(value: string) {
  return value
    .replace(/\*\*/g, "")
    .replace(/^["“]|["”]$/g, "")
    .trim()
    .slice(0, 160);
}

export default function ChatPanel({
  events,
  historyVersion,
  connected,
  conversationStatus,
  conversationLastError,
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
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedMessageIndexes, setSelectedMessageIndexes] = useState<Set<number>>(() => new Set());
  const [quoteReferences, setQuoteReferences] = useState<QuoteReference[]>([]);
  const [visibleStart, setVisibleStart] = useState(0);
  const [liveStart, setLiveStart] = useState(0);
  const displayEvents = useMemo(() => mergeStreamEvents(events), [events]);
  const liveEvents = useMemo(() => displayEvents.slice(liveStart), [displayEvents, liveStart]);
  const taskList = useMemo(() => {
    const latest = [...liveEvents].reverse().find(isTaskListEvent);
    return parseAgentTaskList(latest);
  }, [liveEvents]);
  const workState = useMemo(
    () => liveEvents.length > 0
      ? getWorkState(liveEvents, connected)
      : conversationStatusToWorkState(conversationStatus, conversationLastError, connected),
    [connected, conversationLastError, conversationStatus, liveEvents],
  );
  const visibleEvents = useMemo(() => displayEvents.slice(visibleStart), [displayEvents, visibleStart]);
  const allToolsEnabled = selectedTools === null;
  const enabledToolCount = allToolsEnabled ? tools.length : selectedTools.length;
  const canSend = Boolean(input.trim() && connected && enabledToolCount > 0);
  const quoteSummary = useMemo(() => summarizeQuoteReferences(quoteReferences), [quoteReferences]);
  const visibleSelectableIndexes = useMemo(
    () => visibleEvents
      .map((event, index) => ({ event, index: visibleStart + index }))
      .filter(({ event }) => isSelectableMessage(event))
      .map(({ index }) => index),
    [visibleEvents, visibleStart],
  );
  const selectedMessages = useMemo(
    () => [...selectedMessageIndexes]
      .sort((a, b) => a - b)
      .map((index) => displayEvents[index])
      .filter(Boolean)
      .filter(isSelectableMessage),
    [displayEvents, selectedMessageIndexes],
  );
  const toolSummary = allToolsEnabled
    ? "全部工具"
    : enabledToolCount === 0
      ? "未选择工具"
      : selectedTools.slice(0, 2).join(", ") + (enabledToolCount > 2 ? ` +${enabledToolCount - 2}` : "");

  useEffect(() => {
    const start = Math.max(0, displayEvents.length - INITIAL_HISTORY_WINDOW);
    stickToBottomRef.current = true;
    pendingScrollTargetRef.current = "bottom";
    setLiveStart(displayEvents.length);
    setVisibleStart(start);
    setQuoteReferences([]);
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

  useEffect(() => {
    setSelectedMessageIndexes((current) => {
      const next = new Set<number>();
      for (const index of current) {
        if (isSelectableMessage(displayEvents[index])) next.add(index);
      }
      return next;
    });
  }, [displayEvents]);

  const sendMessage = (content: string) => {
    if (canSend) {
      stickToBottomRef.current = true;
      pendingScrollTargetRef.current = "bottom";
      onSend(content.trim(), selectedTools, {
        modelContent: buildModelMessageWithReferences(content, quoteReferences),
        metadata: {
          quote_reference_count: quoteSummary.messageCount,
          quote_reference_lines: quoteSummary.lineCount,
        },
      });
      onInputChange("");
      setQuoteReferences([]);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) sendMessage(input);
    }
  };

  const handleSend = () => {
    if (canSend) sendMessage(input);
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

  const toggleMessageSelection = (index: number) => {
    setSelectedMessageIndexes((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const selectVisibleMessages = () => {
    setSelectionMode(true);
    setSelectedMessageIndexes((current) => new Set([...current, ...visibleSelectableIndexes]));
  };

  const clearSelectedMessages = () => {
    setSelectedMessageIndexes(new Set());
  };

  const copySelectedMessages = async () => {
    const content = formatSelectedMessages(selectedMessages);
    if (!content) return;
    await navigator.clipboard.writeText(content);
  };

  const quoteSelectedIntoInput = () => {
    const references = quoteReferencesFromEvents(selectedMessages);
    if (!references.length) return;
    setQuoteReferences(references);
  };

  const copySingleMessage = async (event: AgentEvent) => {
    if (!event.content?.trim()) return;
    await navigator.clipboard.writeText(`${messageRoleLabel(event)}：\n${event.content.trim()}`);
  };

  const quoteSingleMessage = (event: AgentEvent) => {
    if (!event.content?.trim()) return;
    setQuoteReferences(quoteReferencesFromEvents([event]));
  };

  const chooseOption = (option: ChoiceOption) => {
    if (!connected) return;
    stickToBottomRef.current = true;
    pendingScrollTargetRef.current = "bottom";
    const content = `我选择：${option.value}`;
    onSend(content, selectedTools, {
      modelContent: buildModelMessageWithReferences(content, quoteReferences),
      metadata: {
        quote_reference_count: quoteSummary.messageCount,
        quote_reference_lines: quoteSummary.lineCount,
      },
    });
    setQuoteReferences([]);
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
          <button
            className={selectionMode ? "btn-secondary" : "btn-ghost"}
            onClick={() => {
              setSelectionMode((value) => !value);
              if (selectionMode) clearSelectedMessages();
            }}
          >
            选择
          </button>
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

      {taskList && (
        <div className={`chat-task-panel${taskList.done ? " is-done" : ""}`}>
          <div className="chat-task-panel-head">
            <strong>Agent 任务</strong>
            <span>{taskList.activeLabel}</span>
          </div>
          <ol className="chat-task-list">
            {taskList.tasks.map((task, index) => (
              <li key={`${task.label}-${index}`} className={`is-${task.status}`}>
                <span className="chat-task-marker" aria-hidden="true" />
                <span>{task.label}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {selectionMode && (
          <div className="chat-selection-bar">
            <span>已选 {selectedMessages.length} 条</span>
            <button className="btn-ghost" onClick={selectVisibleMessages} disabled={visibleSelectableIndexes.length === 0}>
              全选可见
            </button>
            <button className="btn-ghost" onClick={copySelectedMessages} disabled={selectedMessages.length === 0}>
              复制
            </button>
            <button className="btn-ghost" onClick={quoteSelectedIntoInput} disabled={selectedMessages.length === 0}>
              引用
            </button>
            <button className="btn-ghost" onClick={clearSelectedMessages} disabled={selectedMessages.length === 0}>
              清空
            </button>
          </div>
        )}
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
          const eventIndex = visibleStart + i;
          const isUser = event.sender === "user";
          const isSystemStatus = isSystemStatusEvent(event);
          const isError = isErrorEvent(event);
          const isToolStatus = isToolStatusEvent(event);
          const isStreaming = event.type === "stream";
          const isLast = i === visibleEvents.length - 1;
          const selectable = isSelectableMessage(event);
          const selected = selectedMessageIndexes.has(eventIndex);
          const choiceOptions = !isUser && event.type === "agent_final" ? extractChoiceOptions(event.content) : [];
          const userDisplay = isUser ? displayReferencedUserContent(event.content, event.metadata) : null;
          if (isTaskListEvent(event)) return null;
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
            <div
              key={eventIndex}
              className={`chat-message ${isUser ? "chat-message--user" : "chat-message--agent"}${selected ? " is-selected" : ""}${selectionMode && selectable ? " is-selectable" : ""}`}
            >
              {selectionMode && selectable && (
                <label className="chat-message-select" title="选择这条消息">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleMessageSelection(eventIndex)}
                  />
                </label>
              )}
              {!isUser && event.type !== "stream" && (
                <div className="chat-message-type">{event.type}</div>
              )}
              {isUser && event.content && (
                <div className={`chat-message-body${isStreaming && isLast ? " chat-message-body--streaming" : ""}`}>
                  {userDisplay && userDisplay.referenceLines > 0 && (
                    <div className="chat-message-reference-summary">
                      {userDisplay.referenceCount > 1
                        ? `引用 ${userDisplay.referenceCount} 条消息 · ${userDisplay.referenceLines} 行文字`
                        : `引用 ${userDisplay.referenceLines} 行文字`}
                    </div>
                  )}
                  {userDisplay?.content ?? event.content}
                  {isStreaming && isLast && <span className="chat-cursor" />}
                </div>
              )}
              {!isUser && renderAgentContent(event, isStreaming, isLast)}
              {choiceOptions.length > 0 && (
                <div className="chat-choice-options">
                  <span>选择一个继续</span>
                  {choiceOptions.map((option, optionIndex) => (
                    <button
                      key={`${option.value}-${optionIndex}`}
                      className="chat-choice-option"
                      onClick={() => chooseOption(option)}
                      disabled={!connected}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              )}
              {selectable && (
                <div className="chat-message-actions">
                  <button className="btn-ghost" onClick={() => void copySingleMessage(event)}>复制</button>
                  <button className="btn-ghost" onClick={() => quoteSingleMessage(event)}>引用</button>
                  <button className="btn-ghost" onClick={() => toggleMessageSelection(eventIndex)}>
                    {selected ? "取消选择" : "选择"}
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
        {!allToolsEnabled && enabledToolCount === 0 && (
          <p className="chat-input-warning">至少选择一个工具，或恢复默认全部工具。</p>
        )}
        {quoteReferences.length > 0 && (
          <div className="chat-reference-box">
            <div>
              <strong>{quoteSummary.label}</strong>
            </div>
            <button className="btn-ghost" onClick={() => setQuoteReferences([])}>
              取消
            </button>
          </div>
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
