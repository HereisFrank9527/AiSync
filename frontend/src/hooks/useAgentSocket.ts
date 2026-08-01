import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, AgentRunRecord } from "../types";
import { apiBaseToWsBase } from "../config/runtime";
import { api } from "../api/client";

const LIVE_EVENT_LIMIT = 5000;
const LIVE_EVENT_COMPACT_TARGET = 1200;
const COMPACTIBLE_EVENT_TYPES = new Set(["stream", "agent_status", "agent_run"]);
const HEARTBEAT_INTERVAL_MS = 15_000;
const STABLE_CONNECTION_MS = 30_000;

interface SendOptions {
  modelContent?: string;
  metadata?: Record<string, unknown>;
}

function appendLiveEvent(current: AgentEvent[], event: AgentEvent) {
  if (event.type === "changeset_update") {
    const data = event.ui_hint?.data;
    const changeSetId = data && typeof data === "object" && !Array.isArray(data)
      ? String((data as Record<string, unknown>).id ?? "")
      : "";
    if (!changeSetId) return current;
    let index = -1;
    for (let candidate = current.length - 1; candidate >= 0; candidate -= 1) {
      const item = current[candidate];
      const itemData = item.ui_hint?.data;
      if (
        item.type === "tool_result"
        && itemData
        && typeof itemData === "object"
        && !Array.isArray(itemData)
        && String((itemData as Record<string, unknown>).id ?? "") === changeSetId
      ) {
        index = candidate;
        break;
      }
    }
    if (index < 0) return current;
    const next = [...current];
    next[index] = {
      ...next[index],
      content: event.content ?? next[index].content,
      ui_hint: event.ui_hint ?? next[index].ui_hint,
      metadata: { ...next[index].metadata, ...event.metadata },
    };
    return next;
  }
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

function streamRunId(event: AgentEvent) {
  return typeof event.metadata?.run_id === "string" ? event.metadata.run_id : "";
}

function streamVersion(event: AgentEvent) {
  return typeof event.metadata?.stream_version === "number" ? event.metadata.stream_version : 0;
}

function reconcileRunDraft(events: AgentEvent[], run: AgentRunRecord) {
  if (!run.draft_content || run.draft_version <= 0) return events;
  const withoutOlderDraft = events.filter(
    (event) => event.type !== "stream" || streamRunId(event) !== run.run_id,
  );
  return compactLiveEvents([
    ...withoutOlderDraft,
    {
      type: "stream",
      content: run.draft_content,
      sender: "agent",
      conversation_id: run.conversation_id,
      metadata: {
        run_id: run.run_id,
        stream_version: run.draft_version,
        restored_from_run: true,
      },
    },
  ]);
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
  const conversationIdRef = useRef<string | null>(conversationId);
  const socketRef = useRef<WebSocket | null>(null);
  const activeRunRef = useRef<AgentRunRecord | null>(null);
  const streamVersionsRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  const applyActiveRun = useCallback((incoming: AgentRunRecord) => {
    const current = activeRunRef.current;
    const run = current
      && current.run_id === incoming.run_id
      && incoming.status === "running"
      && current.draft_version > incoming.draft_version
      ? {
          ...incoming,
          draft_content: current.draft_content,
          draft_version: current.draft_version,
          draft_updated_at: current.draft_updated_at,
        }
      : incoming;
    activeRunRef.current = run;
    setActiveRun(run);
    if (!run.draft_content || run.draft_version <= 0) return;
    const knownVersion = streamVersionsRef.current.get(run.run_id) ?? 0;
    if (run.draft_version < knownVersion) return;
    streamVersionsRef.current.set(run.run_id, run.draft_version);
    setEvents((currentEvents) => reconcileRunDraft(currentEvents, run));
  }, []);

  const refreshLatestRun = useCallback(async (targetConversationId: string) => {
    if (!projectPath) return;
    const params = new URLSearchParams({ project_path: projectPath, conversation_id: targetConversationId });
    try {
      const run = await api.get<AgentRunRecord | null>(`/agent/current/runs/latest?${params.toString()}`);
      if (conversationIdRef.current !== targetConversationId) return;
      if (run) {
        applyActiveRun(run);
      } else {
        activeRunRef.current = null;
        setActiveRun(null);
      }
    } catch {
      // A reconnect can race with backend startup; keep the last known run until the next refresh.
    }
  }, [applyActiveRun, projectPath]);

  useEffect(() => {
    if (!projectPath) {
      setEvents([]);
      return;
    }

    let closedByEffect = false;
    let reconnectTimer: number | null = null;
    let attempt = 0;

    const connect = () => {
      if (closedByEffect) return;
      const encodedPath = encodeURIComponent(projectPath);
      const socket = new WebSocket(`${apiBaseToWsBase()}/api/agent/current/ws?project_path=${encodedPath}`);
      socketRef.current = socket;
      let heartbeatTimer: number | null = null;
      let stableConnectionTimer: number | null = null;

      const clearConnectionTimers = () => {
        if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer);
        if (stableConnectionTimer !== null) window.clearTimeout(stableConnectionTimer);
        heartbeatTimer = null;
        stableConnectionTimer = null;
      };

      socket.onopen = () => {
        if (socketRef.current !== socket) {
          socket.close();
          return;
        }
        setConnected(true);
        const currentConversationId = conversationIdRef.current;
        if (currentConversationId) void refreshLatestRun(currentConversationId);
        heartbeatTimer = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
        }, HEARTBEAT_INTERVAL_MS);
        stableConnectionTimer = window.setTimeout(() => {
          if (socket.readyState === WebSocket.OPEN) attempt = 0;
        }, STABLE_CONNECTION_MS);
      };
      socket.onclose = () => {
        clearConnectionTimers();
        if (socketRef.current !== socket) return;
        socketRef.current = null;
        setConnected(false);
        if (closedByEffect) return;
        const delay = Math.min(1000 * 2 ** attempt, 10000);
        attempt += 1;
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, delay);
      };
      socket.onerror = () => {
        if (socketRef.current === socket) setConnected(false);
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as AgentEvent;
          if (event.type === "pong") {
            if (socketRef.current === socket) setConnected(true);
            return;
          }
          if (event.type === "conversation" && event.conversation_id) {
            if (conversationIdRef.current) return;
            conversationIdRef.current = event.conversation_id;
            onConversationIdChange?.(event.conversation_id);
            return;
          }
          if (event.conversation_id && event.conversation_id !== conversationIdRef.current) return;
          if (event.type === "agent_run" && event.run) {
            applyActiveRun(event.run);
            return;
          }
          if (event.type === "stream") {
            const runId = streamRunId(event);
            const version = streamVersion(event);
            if (runId && version > 0) {
              const knownVersion = streamVersionsRef.current.get(runId) ?? 0;
              if (version <= knownVersion) return;
              streamVersionsRef.current.set(runId, version);
              const run = activeRunRef.current;
              if (run?.run_id === runId) {
                activeRunRef.current = {
                  ...run,
                  draft_content: `${run.draft_content ?? ""}${event.content ?? ""}`,
                  draft_version: version,
                  draft_updated_at: new Date().toISOString(),
                };
              }
            }
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
  }, [applyActiveRun, onConversationIdChange, projectPath, refreshLatestRun]);

  useEffect(() => {
    if (!projectPath || !conversationId) {
      activeRunRef.current = null;
      setActiveRun(null);
      return;
    }
    if (activeRunRef.current?.conversation_id !== conversationId) {
      activeRunRef.current = null;
      setActiveRun(null);
    }
    void refreshLatestRun(conversationId);
  }, [conversationId, projectPath, refreshLatestRun]);

  const setPresetId = useCallback((id: string | null) => {
    presetRef.current = id;
  }, []);

  const setHistory = useCallback((history: AgentEvent[]) => {
    streamVersionsRef.current.clear();
    const run = activeRunRef.current;
    if (run && run.conversation_id === conversationIdRef.current && run.draft_content && run.draft_version > 0) {
      streamVersionsRef.current.set(run.run_id, run.draft_version);
      setEvents(reconcileRunDraft(history, run));
    } else {
      setEvents(history);
    }
    setHistoryVersion((current) => current + 1);
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
    activeRunRef.current = null;
    streamVersionsRef.current.clear();
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
      activeRunRef.current = null;
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
    if (conversationId) payload.conversation_id = conversationId;
    if (activeRun?.run_id) payload.run_id = activeRun.run_id;
    socketRef.current?.send(JSON.stringify(payload));
    setActiveRun((current) => {
      if (!current || current.status !== "running") return current;
      const now = new Date().toISOString();
      return {
        ...current,
        status: "interrupted",
        phase: "interrupt_requested",
        phase_label: "已请求中断",
        updated_at: now,
        finished_at: now,
        error: "用户已请求中断，正在等待底层模型请求返回。",
      };
    });
    setEvents((current) =>
      appendLiveEvent(current, { type: "agent_status", content: "正在请求中断当前回复", sender: "agent" }),
    );

    if (!projectPath) return;
    const params = new URLSearchParams({ project_path: projectPath });
    if (presetRef.current) params.set("preset_id", presetRef.current);
    if (conversationId) params.set("conversation_id", conversationId);
    if (activeRun?.run_id) params.set("run_id", activeRun.run_id);
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
  }, [activeRun?.run_id, conversationId, projectPath]);

  const retryRun = useCallback((runId: string) => {
    if (!runId) return;
    const payload: Record<string, unknown> = { type: "retry_run", run_id: runId };
    if (conversationId) payload.conversation_id = conversationId;
    socketRef.current?.send(JSON.stringify(payload));
    setActiveRun(null);
    setEvents((current) => appendLiveEvent(current, {
      type: "agent_status",
      content: "正在准备恢复本轮运行",
      sender: "agent",
      metadata: { phase: "retrying", retry_of_run_id: runId },
    }));
  }, [conversationId]);

  return {
    connected,
    events,
    historyVersion,
    activeRun,
    send,
    interrupt,
    retryRun,
    setPresetId,
    setHistory,
    clearEvents,
  };
}
