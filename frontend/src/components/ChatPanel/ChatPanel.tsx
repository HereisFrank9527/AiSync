import { useMemo, useRef, useEffect, type KeyboardEvent } from "react";
import type { AgentEvent } from "../../types";
import "./ChatPanel.css";

interface ChatPanelProps {
  events: AgentEvent[];
  connected: boolean;
  onSend: (content: string) => void;
  onInterrupt: () => void;
  input: string;
  onInputChange: (value: string) => void;
  showConversations?: boolean;
  onToggleConversations?: () => void;
}

/** 合并连续的 stream 事件为单条消息，去除 stream_end */
function mergeStreamEvents(events: AgentEvent[]): AgentEvent[] {
  const merged: AgentEvent[] = [];
  for (const event of events) {
    if (event.type === "stream_end") continue;
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

export default function ChatPanel({
  events,
  connected,
  onSend,
  onInterrupt,
  input,
  onInputChange,
  showConversations,
  onToggleConversations,
}: ChatPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const displayEvents = useMemo(() => mergeStreamEvents(events), [events]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (input.trim() && connected) {
        onSend(input);
        onInputChange("");
      }
    }
  };

  const handleSend = () => {
    if (input.trim() && connected) {
      onSend(input);
      onInputChange("");
    }
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
          <button
            className="btn-ghost"
            onClick={onInterrupt}
            disabled={!connected}
          >
            中断
          </button>
        </div>
      </header>

      <div className="chat-messages">
        {displayEvents.length === 0 && (
          <div className="chat-empty">发送消息开始对话</div>
        )}
        {displayEvents.map((event, i) => {
          const isUser = event.sender === "user";
          const isStreaming = event.type === "stream";
          const isLast = i === displayEvents.length - 1;
          return (
            <div key={i} className={`chat-message ${isUser ? "chat-message--user" : "chat-message--agent"}`}>
              {!isUser && event.type !== "stream" && (
                <div className="chat-message-type">{event.type}</div>
              )}
              {event.content && (
                <div className={`chat-message-body${isStreaming && isLast ? " chat-message-body--streaming" : ""}`}>
                  {event.content}
                  {isStreaming && isLast && <span className="chat-cursor" />}
                </div>
              )}
              {event.ui_hint && (
                <pre className="chat-message-hint">
                  {JSON.stringify(event.ui_hint, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
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
            disabled={!input.trim() || !connected}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
