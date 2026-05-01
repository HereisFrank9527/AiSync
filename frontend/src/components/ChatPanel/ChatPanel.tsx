import { useRef, useEffect, type KeyboardEvent } from "react";
import type { AgentEvent } from "../../types";
import "./ChatPanel.css";

interface ChatPanelProps {
  events: AgentEvent[];
  connected: boolean;
  onSend: (content: string) => void;
  onInterrupt: () => void;
  input: string;
  onInputChange: (value: string) => void;
}

export default function ChatPanel({
  events,
  connected,
  onSend,
  onInterrupt,
  input,
  onInputChange,
}: ChatPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

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
        <h2>对话</h2>
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
        {events.length === 0 && (
          <div className="chat-empty">发送消息开始对话</div>
        )}
        {events.map((event, i) => (
          <div key={i} className="chat-message">
            <div className="chat-message-type">{event.type}</div>
            {event.content && (
              <div className="chat-message-body">{event.content}</div>
            )}
            {event.ui_hint && (
              <pre className="chat-message-hint">
                {JSON.stringify(event.ui_hint, null, 2)}
              </pre>
            )}
          </div>
        ))}
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
