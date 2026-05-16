import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, AgentRunRecord } from "../types";
import { apiBaseToWsBase } from "../config/runtime";
import { api } from "../api/client";

const LIVE_EVENT_LIMIT = 5000;
const LIVE_EVENT_COMPACT_TARGET = 1200;
const COMPACTIBLE_EVENT_TYPES = new Set(["stream", "agent_status", "agent_run"]);

interface SendOptions {
  modelContent?: string;
  metadata?: Record<string, unknown>;
}

function appendLiveEvent(current: AgentEvent[], event: AgentEvent) {
  if (event.type === "agent_final") {
    const last = current[current.length - 1];
    if (
      last?.type === "agent_final" &&
      last.conversation_id === event.conversation_id &&
      last.content === event.content
    ) {
      return current;
    }
  }
  const next = [...current, event];
  return compactLiveEvents(next);
}

function compactLiveEvents(events: AgentEvent[]) {
  if (events.length <= LIVE_EVENT_LIMIT) return events;
  const protectedEvents = events.filter((event) => !COMPACTIBLE_EVENT_TYPES.has(event.type));
  const recent = events.slice(-LIVE_EVENT_COMPACT_TARGET);
  const protectedRecentIds = new Set(recent.map((event) => event));
  const olderProtected = protectedEvents.filter((event) => !protectedRecentIds.has(event));
  return [...olderProtected, ...recent].slice(-LIVE_EVENT_LIMIT);
}

export function useAgentSocket(
  projectPath: string | null,
  conversationId: string | null,
  onConversationIdChange?: (conversationId: string) => void,
) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [activeRun, setActiveRun] = useState<AgentRunRecord | null>(null);
  const [connected, setConnected] = useState(false);
  const [historyVersion, setHistoryVersion] = useState(0);
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
      const socket = new WebSocket(`${apiBaseToWsBase()}/api/agent/current/ws?project_path=${encodedPath}`);
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
          if (event.type === "agent_run" && event.run) {
            setActiveRun(event.run);
            return;
          }
          if (!event.sender) event.sender = "agent";
          setEvents((current) => appendLiveEvent(current, event));
        } catch {
          setEvents((current) => appendLiveEvent(current, { type: "error", content: "收到无法解析的后端消息" }));
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

  useEffect(() => {
    if (!projectPath || !conversationId) {
      setActiveRun(null);
      return;
    }
    const params = new URLSearchParams({ project_path: projectPath, conversation_id: conversationId });
    let cancelled = false;
    void api
      .get<AgentRunRecord | null>(`/agent/current/runs/latest?${params.toString()}`)
      .then((run) => {
        if (!cancelled) setActiveRun(run);
      })
      .catch(() => {
        if (!cancelled) setActiveRun(null);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, projectPath]);

  const setPresetId = useCallback((id: string | null) => {
    presetRef.current = id;
  }, []);

  const setHistory = useCallback((history: AgentEvent[]) => {
    setEvents(history);
    setHistoryVersion((current) => current + 1);
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
    setActiveRun(null);
    setHistoryVersion((current) => current + 1);
  }, []);

  const send = useCallback(
    (content: string, enabledTools?: string[] | null, options?: SendOptions) => {
      const payload: Record<string, unknown> = { type: "user_message", content };
      if (options?.modelContent && options.modelContent !== content) payload.model_content = options.modelContent;
      if (options?.metadata) payload.metadata = options.metadata;
      if (presetRef.current) payload.preset_id = presetRef.current;
      if (conversationId) payload.conversation_id = conversationId;
      if (enabledTools !== undefined) payload.enabled_tools = enabledTools;
      socketRef.current?.send(JSON.stringify(payload));
      setActiveRun(null);
      setEvents((current) =>
        appendLiveEvent(current, { type: "user_message", content, sender: "user" as const, metadata: options?.metadata }),
      );
    },
    [conversationId],
  );

  const interrupt = useCallback(() => {
    const payload: Record<string, unknown> = { type: "interrupt" };
    if (presetRef.current) payload.preset_id = presetRef.current;
    socketRef.current?.send(JSON.stringify(payload));
    setEvents((current) =>
      appendLiveEvent(current, { type: "agent_status", content: "正在请求中断当前回复", sender: "agent" }),
    );

    if (!projectPath) return;
    const params = new URLSearchParams({ project_path: projectPath });
    if (presetRef.current) params.set("preset_id", presetRef.current);
    void api
      .post<{ status: string; interrupted: boolean }>(`/agent/current/interrupt?${params.toString()}`, {})
      .then((response) => {
        setEvents((current) =>
          appendLiveEvent(current, {
            type: "agent_status",
            content: response.interrupted ? "已请求中断当前回复" : "当前没有正在运行的 Agent",
            sender: "agent",
            metadata: { phase: "interrupt_requested", interrupted: response.interrupted },
          }),
        );
      })
      .catch((error) => {
        setEvents((current) =>
          appendLiveEvent(current, {
            type: "error",
            content: `中断请求失败：${error instanceof Error ? error.message : String(error)}`,
          }),
        );
      });
  }, [projectPath]);

  return { connected, events, historyVersion, activeRun, send, interrupt, setPresetId, setHistory, clearEvents };
}
