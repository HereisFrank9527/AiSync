import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import ChatPanel from "./components/ChatPanel";
import ConversationList from "./components/ConversationList";
import FileTree from "./components/FileTree";
import FileView from "./components/FileView";
import Sidebar from "./components/Sidebar";
import SettingsPanel from "./components/SettingsPanel";
import ToolDrawer from "./components/ToolDrawer";
import ToolsPanel from "./components/ToolsPanel";
import { useAgentSocket } from "./hooks/useAgentSocket";
import { useConversations } from "./hooks/useConversations";
import { useFileTree } from "./hooks/useFileTree";
import { usePresets } from "./hooks/usePresets";
import { useProject } from "./hooks/useProject";
import { useTools } from "./hooks/useTools";
import type { AgentEvent, ConversationMessage, ToolDescriptor, ViewId } from "./types";
import "./style.css";

function conversationMessagesToEvents(messages: ConversationMessage[]): AgentEvent[] {
  return messages.map((message) => ({
    type: message.type,
    content: message.content,
    sender: message.role,
  }));
}

function App() {
  const { project, selectFolder } = useProject();
  const [activeView, setActiveView] = useState<ViewId>("chat");
  const [input, setInput] = useState("");
  const [selectedTool, setSelectedTool] = useState<ToolDescriptor | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedFileContent, setSelectedFileContent] = useState("");
  const [fileSaving, setFileSaving] = useState(false);
  const [showConversations, setShowConversations] = useState(false);
  const projectInitRef = useRef<string | null>(null);

  const conversations = useConversations(project?.path ?? null);
  const fileTree = useFileTree(project?.path ?? null);
  const presets = usePresets();
  const tools = useTools(project?.path ?? null, presets.activeId);

  const handleConversationIdChange = useCallback((conversationId: string) => {
    conversations.setActiveConversationId(conversationId);
    void conversations.refresh();
  }, [conversations.refresh, conversations.setActiveConversationId]);

  const { connected, events, send, interrupt, setPresetId, setHistory, clearEvents } =
    useAgentSocket(project?.path ?? null, conversations.activeConversationId, handleConversationIdChange);

  useEffect(() => {
    setPresetId(presets.activeId);
  }, [presets.activeId, setPresetId]);

  // 项目切换时：初始化目录结构 + 清空状态
  useEffect(() => {
    if (!project?.path) return;
    // 同一项目不重复初始化
    if (projectInitRef.current === project.path) return;
    projectInitRef.current = project.path;
    initializedRef.current = false;

    clearEvents();
    setInput("");
    setSelectedFilePath(null);
    setSelectedFileContent("");
    conversations.setActiveConversation(null);
    conversations.setActiveConversationId(null);
    void conversations.refresh();
    api.post("/projects/init", { project_path: project.path })
      .then(() => fileTree.refresh())
      .catch(() => fileTree.refresh());
  }, [project?.path]); // eslint-disable-line react-hooks/exhaustive-deps

  // 首次加载对话列表后自动打开第一条或创建新对话
  const initializedRef = useRef(false);
  useEffect(() => {
    if (!project?.path) return;
    if (conversations.activeConversationId) return;
    if (conversations.loading) return;
    if (initializedRef.current) return;
    if (conversations.items.length > 0) {
      initializedRef.current = true;
      const rememberedId = conversations.rememberedConversationId();
      const target = conversations.items.find((item) => item.id === rememberedId) ?? conversations.items[0];
      void conversations.load(target.id).then((conv) => {
        if (conv) setHistory(conversationMessagesToEvents(conv.messages));
      });
      return;
    }
    // 没有对话，创建一条
    initializedRef.current = true;
    void conversations.create();
  }, [conversations.activeConversationId, conversations.items, conversations.loading, project?.path]); // eslint-disable-line react-hooks/exhaustive-deps

  const openConversation = useCallback(async (conversationId: string) => {
    const conversation = await conversations.load(conversationId);
    if (!conversation) return;
    setHistory(conversationMessagesToEvents(conversation.messages));
    setInput("");
  }, [conversations.load, setHistory]);

  const handleNewConversation = useCallback(async () => {
    const conversation = await conversations.create();
    if (!conversation) return;
    clearEvents();
    setHistory([]);
    setInput("");
  }, [clearEvents, conversations.create, setHistory]);

  const handleDeleteConversation = useCallback(async (conversationId: string) => {
    if (!window.confirm("确定删除这个对话？")) return;
    await conversations.remove(conversationId);
    clearEvents();
    setHistory([]);
    setInput("");
  }, [clearEvents, conversations.remove, setHistory]);

  const handleOpenFile = useCallback(async (path: string) => {
    setSelectedFilePath(path);
    if (!project?.path) return;
    const response = await api.get<{ path: string; content: string }>(
      `/projects/files/${path}?project_path=${encodeURIComponent(project.path)}`,
    );
    setSelectedFileContent(response.content);
    setActiveView("files");
  }, [project?.path]);

  const handleSaveFile = useCallback(async () => {
    if (!project?.path || !selectedFilePath) return;
    setFileSaving(true);
    try {
      await api.put(`/projects/files/${selectedFilePath}?project_path=${encodeURIComponent(project.path)}`, {
        content: selectedFileContent,
      });
      await fileTree.refresh();
    } finally {
      setFileSaving(false);
    }
  }, [fileTree.refresh, project?.path, selectedFileContent, selectedFilePath]);

  return (
    <div className="app-shell">
      <Sidebar
        projectName={project?.name ?? "未选择"}
        projectPath={project?.path ?? ""}
        connected={connected}
        activeView={activeView}
        onViewChange={setActiveView}
        onSelectFolder={() => void selectFolder()}
      />

      <main className="main-content">
        {activeView === "chat" && (
          <div className="chat-workspace">
            {showConversations && (
              <ConversationList
                items={conversations.items}
                activeId={conversations.activeConversationId}
                loading={conversations.loading}
                error={conversations.error}
                onNew={handleNewConversation}
                onSelect={(id) => { openConversation(id); setShowConversations(false); }}
                onDelete={handleDeleteConversation}
              />
            )}
            <div className="chat-workspace-main">
              <ChatPanel
                events={events}
                connected={connected}
                onSend={send}
                onInterrupt={interrupt}
                input={input}
                onInputChange={setInput}
                showConversations={showConversations}
                onToggleConversations={() => setShowConversations((v) => !v)}
              />
            </div>
          </div>
        )}

        {activeView === "files" && (
          <div className="files-workspace">
            <aside className="files-sidebar">
              <header className="files-sidebar-header">
                <h2>文件树</h2>
                <button className="btn-secondary" onClick={() => void fileTree.refresh()}>
                  刷新
                </button>
              </header>
              {fileTree.loading && <p className="files-muted">加载中…</p>}
              {fileTree.error && <p className="files-error">{fileTree.error}</p>}
              <FileTree tree={fileTree.tree} activePath={selectedFilePath} onOpenFile={handleOpenFile} />
            </aside>
            <div className="files-editor">
              <FileView
                path={selectedFilePath}
                content={selectedFileContent}
                onChange={setSelectedFileContent}
                onSave={handleSaveFile}
                saving={fileSaving}
              />
            </div>
          </div>
        )}

        {activeView === "settings" && presets.loading && (
          <div className="view-status view-status--loading">加载预设中…</div>
        )}
        {activeView === "settings" && presets.error && (
          <div className="view-status view-status--error">{presets.error}</div>
        )}
        {activeView === "settings" && !presets.loading && !presets.error && (
          <SettingsPanel
            presets={presets.presets}
            activeId={presets.activeId}
            activePreset={presets.activePreset}
            onSelect={presets.setActiveId}
            onCreate={presets.create}
            onUpdate={presets.update}
            onDelete={presets.remove}
            isBuiltin={presets.isBuiltin}
          />
        )}

        {activeView === "tools" && (
          <ToolsPanel
            tools={tools.tools}
            loading={tools.loading}
            error={tools.error}
            onSelect={setSelectedTool}
          />
        )}
      </main>

      <ToolDrawer
        tool={selectedTool}
        result={tools.result}
        error={tools.error}
        running={tools.running}
        onClose={() => setSelectedTool(null)}
        onExecute={tools.execute}
        onInvoke={tools.invoke}
      />
    </div>
  );
}

export default App;
