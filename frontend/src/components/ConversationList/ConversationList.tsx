import type { ConversationSummary } from "../../types";
import "./ConversationList.css";

interface ConversationListProps {
  items: ConversationSummary[];
  activeId: string | null;
  loading: boolean;
  error: string;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString();
}

export default function ConversationList({
  items,
  activeId,
  loading,
  error,
  onNew,
  onSelect,
  onDelete,
}: ConversationListProps) {
  return (
    <aside className="conversation-list">
      <div className="conversation-list-header">
        <h3>历史对话</h3>
        <button className="btn-secondary" onClick={onNew}>新建</button>
      </div>
      {loading && <p className="conversation-muted">加载中…</p>}
      {error && <p className="conversation-error">{error}</p>}
      {!loading && !error && items.length === 0 && <p className="conversation-muted">暂无历史对话</p>}
      <div className="conversation-items">
        {items.map((item) => (
          <div key={item.id} className={`conversation-item${activeId === item.id ? " active" : ""}`}>
            <button className="conversation-main" onClick={() => onSelect(item.id)}>
              <span>{item.title}</span>
              <small>{formatTime(item.updated_at)} · {item.message_count} 条</small>
            </button>
            <button
              className="conversation-delete"
              onClick={() => onDelete(item.id)}
              title="删除对话"
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
