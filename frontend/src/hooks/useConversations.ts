import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Conversation, ConversationSummary } from "../types";

const ACTIVE_CONVERSATION_PREFIX = "aisync:activeConversation:";

export function useConversations(projectPath: string | null) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [activeConversationId, setActiveConversationIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadedProjectPath, setLoadedProjectPath] = useState<string | null>(null);
  const [error, setError] = useState("");

  const storageKey = useMemo(
    () => projectPath ? `${ACTIVE_CONVERSATION_PREFIX}${projectPath}` : null,
    [projectPath],
  );

  const setActiveConversationId = useCallback((conversationId: string | null) => {
    setActiveConversationIdState(conversationId);
    if (!storageKey) return;
    if (conversationId) localStorage.setItem(storageKey, conversationId);
    else localStorage.removeItem(storageKey);
  }, [storageKey]);

  const rememberedConversationId = useCallback(() => {
    return storageKey ? localStorage.getItem(storageKey) : null;
  }, [storageKey]);

  const refresh = useCallback(async () => {
    if (!projectPath) {
      setItems([]);
      setActiveConversation(null);
      setActiveConversationId(null);
      setLoadedProjectPath(null);
      return;
    }

    setLoading(true);
    try {
      const list = await api.get<ConversationSummary[]>(`/conversations?project_path=${encodeURIComponent(projectPath)}`);
      setItems(list);
      setLoadedProjectPath(projectPath);
      setError("");
    } catch {
      setLoadedProjectPath(projectPath);
      setError("无法加载对话历史");
    } finally {
      setLoading(false);
    }
  }, [projectPath, setActiveConversationId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = useCallback(async (title = "新对话") => {
    if (!projectPath) return null;
    const conversation = await api.post<Conversation>("/conversations", {
      title,
      project_path: projectPath,
    });
    setActiveConversation(conversation);
    setActiveConversationId(conversation.id);
    await refresh();
    return conversation;
  }, [projectPath, refresh, setActiveConversationId]);

  const load = useCallback(async (conversationId: string) => {
    if (!projectPath) return null;
    const conversation = await api.get<Conversation>(`/conversations/${conversationId}?project_path=${encodeURIComponent(projectPath)}`);
    setActiveConversation(conversation);
    setActiveConversationId(conversation.id);
    return conversation;
  }, [projectPath, setActiveConversationId]);

  const remove = useCallback(async (conversationId: string) => {
    if (!projectPath) return;
    await api.del(`/conversations/${conversationId}?project_path=${encodeURIComponent(projectPath)}`);
    if (activeConversationId === conversationId) {
      setActiveConversation(null);
      setActiveConversationId(null);
    }
    await refresh();
  }, [activeConversationId, projectPath, refresh, setActiveConversationId]);

  return {
    items,
    activeConversation,
    activeConversationId,
    loading,
    loadedProjectPath,
    error,
    refresh,
    create,
    load,
    remove,
    rememberedConversationId,
    setActiveConversationId,
    setActiveConversation,
  };
}
