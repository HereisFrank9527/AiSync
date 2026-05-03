import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent } from "../types";

export function useAgentSocket(
  projectPath: string | null,
  conversationId: string | null,
  onConversationIdChange?: (conversationId: string) => void,
) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const presetRef = useRef<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!projectPath) {
      setEvents([]);
      return;
    }

    let closedByEffect = false;
    let reconnectTimer: number | null = null;
    let attempt = 0;

    const connect = () => {
      const encodedPath = encodeURIComponent(projectPath);
      const socket = new WebSocket(`ws://localhost:8000/api/agent/current/ws?project_path=${encodedPath}`);
      socketRef.current = socket;

      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onclose = () => {
        setConnected(false);
        if (closedByEffect) return;
        const delay = Math.min(1000 * 2 ** attempt, 10000);
        attempt += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => setConnected(false);
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as AgentEvent;
          if (event.type === "conversation" && event.conversation_id) {
            onConversationIdChange?.(event.conversation_id);
            return;
          }
          if (!event.sender) event.sender = "agent";
          setEvents((current) => [...current, event].slice(-200));
        } catch {
          setEvents((current) => [
            ...current,
            { type: "error", content: "收到无法解析的后端消息" },
          ].slice(-200));
        }
      };
    };

    connect();

    return () => {
      closedByEffect = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
      setConnected(false);
    };
  }, [onConversationIdChange, projectPath]);

  const setPresetId = useCallback((id: string | null) => {
    presetRef.current = id;
  }, []);

  const setHistory = useCallback((history: AgentEvent[]) => {
    setEvents(history.slice(-200));
  }, []);

  const clearEvents = useCallback(() => setEvents([]), []);

  const send = useCallback(
    (content: string) => {
      const payload: Record<string, unknown> = { type: "user_message", content };
      if (presetRef.current) payload.preset_id = presetRef.current;
      if (conversationId) payload.conversation_id = conversationId;
      socketRef.current?.send(JSON.stringify(payload));
      setEvents((current) =>
        [...current, { type: "user_message", content, sender: "user" as const }].slice(-200),
      );
    },
    [conversationId],
  );

  const interrupt = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "interrupt" }));
  }, []);

  return { connected, events, send, interrupt, setPresetId, setHistory, clearEvents };
}
