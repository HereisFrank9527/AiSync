import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent } from "../types";

export function useAgentSocket(projectId: string) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const presetRef = useRef<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!projectId) return;

    let closedByEffect = false;
    let reconnectTimer: number | null = null;
    let attempt = 0;

    const connect = () => {
      const socket = new WebSocket(`ws://localhost:8000/api/agent/${projectId}/ws`);
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
          setEvents((current) => [...current, JSON.parse(message.data)].slice(-200));
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
  }, [projectId]);

  /** Keep preset ref in sync without re-creating callbacks. */
  const setPresetId = useCallback((id: string | null) => {
    presetRef.current = id;
  }, []);

  const send = useCallback(
    (content: string) => {
      const payload: Record<string, unknown> = { type: "user_message", content };
      if (presetRef.current) payload.preset_id = presetRef.current;
      socketRef.current?.send(JSON.stringify(payload));
    },
    [],
  );

  const interrupt = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "interrupt" }));
  }, []);

  return { connected, events, send, interrupt, setPresetId };
}
