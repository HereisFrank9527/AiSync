import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api/client";
import ChatPanel from "./components/ChatPanel";
import ConversationList from "./components/ConversationList";
import FileTree from "./components/FileTree";
import FileView from "./components/FileView";
import OverviewPanel from "./components/OverviewPanel";
import Sidebar from "./components/Sidebar";
import SettingsPanel from "./components/SettingsPanel";
import ToolDrawer from "./components/ToolDrawer";
import ToolsPanel from "./components/ToolsPanel";
import VectorPanel from "./components/VectorPanel";
import { useAgentSocket } from "./hooks/useAgentSocket";
import { useCharacters } from "./hooks/useCharacters";
import { useChapters } from "./hooks/useChapters";
import { useConversations } from "./hooks/useConversations";
import { useFileTree } from "./hooks/useFileTree";
import { useForeshadows } from "./hooks/useForeshadows";
import { useOutline } from "./hooks/useOutline";
import { usePresets } from "./hooks/usePresets";
import { useProject } from "./hooks/useProject";
import { useProjectOverview, withProjectName } from "./hooks/useProjectOverview";
import { useTools } from "./hooks/useTools";
import { useVectorIndex } from "./hooks/useVectorIndex";
import { useWorldview } from "./hooks/useWorldview";
import type { AgentEvent, ConversationMessage, ToolDescriptor, ToolRunRecord, ToolWorkspaceView, ViewId } from "./types";
import { renderRegisteredWorkspaceView, supportedWorkspaceViewIds } from "./workspaceViews";
import "./style.css";

function conversationMessagesToEvents(messages: ConversationMessage[]): AgentEvent[] {
  return messages.map((message) => ({
    type: message.type,
    content: message.content,
    sender: message.role,
  }));
}

function App() {
  const { project, setProject, selectFolder } = useProject();
  const [activeView, setActiveView] = useState<ViewId>("overview");
  const [input, setInput] = useState("");
  const [selectedTool, setSelectedTool] = useState<ToolDescriptor | null>(null);
  const [selectedToolRun, setSelectedToolRun] = useState<ToolRunRecord | null>(null);
  const [toolInitialParams, setToolInitialParams] = useState<Record<string, unknown> | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedFileContent, setSelectedFileContent] = useState("");
  const [fileSaving, setFileSaving] = useState(false);
  const [showConversations, setShowConversations] = useState(false);
  const projectInitRef = useRef<string | null>(null);

  const handleProjectNameChange = useCallback((name: string) => {
    setProject((current) => current && current.name !== name ? withProjectName(current, name) : current);
  }, [setProject]);

  const conversations = useConversations(project?.path ?? null);
  const fileTree = useFileTree(project?.path ?? null);
  const overview = useProjectOverview(project?.path ?? null, handleProjectNameChange);
  const chapters = useChapters(project?.path ?? null);
  const outline = useOutline(project?.path ?? null);
  const foreshadows = useForeshadows(project?.path ?? null);
  const characters = useCharacters(project?.path ?? null);
  const worldview = useWorldview(project?.path ?? null);
  const presets = usePresets();
  const tools = useTools(project?.path ?? null, presets.activeId);
  const vectorIndex = useVectorIndex(project?.path ?? null);
  const implementedToolViewIds = useMemo(() => supportedWorkspaceViewIds(), []);
  const toolViews = useMemo<ToolWorkspaceView[]>(() => {
    const views = tools.tools
      .map((tool) => tool.workspace_view)
      .filter((view): view is ToolWorkspaceView => Boolean(view));
    const unique = new Map<ViewId, ToolWorkspaceView>();
    for (const view of views) {
      if (implementedToolViewIds.has(view.view_id as ViewId)) unique.set(view.view_id as ViewId, view);
    }
    return [...unique.values()];
  }, [implementedToolViewIds, tools.tools]);
  const activeToolView = toolViews.find((view) => view.view_id === activeView);

  useEffect(() => {
    if (implementedToolViewIds.has(activeView) && !tools.loading && !activeToolView) {
      setActiveView("tools");
    }
  }, [activeToolView, activeView, implementedToolViewIds, tools.loading]);

  const handleConversationIdChange = useCallback((conversationId: string) => {
    conversations.setActiveConversationId(conversationId);
    void conversations.refresh();
  }, [conversations.refresh, conversations.setActiveConversationId]);

  const { connected, events, historyVersion, activeRun, send, interrupt, setPresetId, setHistory, clearEvents } =
    useAgentSocket(project?.path ?? null, conversations.activeConversationId, handleConversationIdChange);

  const lastEvent = events[events.length - 1];

  useEffect(() => {
    if (!lastEvent || !conversations.activeConversationId) return;
    const phase = typeof lastEvent.metadata?.phase === "string" ? lastEvent.metadata.phase : "";
    const shouldRefresh =
      lastEvent.type === "agent_final" ||
      lastEvent.type === "error" ||
      phase === "interrupted" ||
      phase === "interrupt_requested";
    if (!shouldRefresh) return;
    void conversations.refresh();
    void conversations.load(conversations.activeConversationId);
  }, [lastEvent, conversations.activeConversationId]); // eslint-disable-line react-hooks/exhaustive-deps

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
    if (conversations.loadedProjectPath !== project.path) return;
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
      void vectorIndex.refresh();
    } finally {
      setFileSaving(false);
    }
  }, [fileTree.refresh, project?.path, selectedFileContent, selectedFilePath, vectorIndex.refresh]);

  return (
    <div className="app-shell">
      <Sidebar
        projectName={project?.name ?? "未选择"}
        projectPath={project?.path ?? ""}
        connected={connected}
        activeView={activeView}
        toolViews={toolViews}
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
                historyVersion={historyVersion}
                connected={connected}
                conversationStatus={conversations.activeConversation?.status ?? null}
                conversationLastError={conversations.activeConversation?.last_error ?? null}
                activeRun={activeRun}
                tools={tools.tools}
                onSend={send}
                onInterrupt={interrupt}
                onRetryLast={() => {
                  if (!activeRun?.input_preview) return;
                  send(activeRun.input_preview);
                }}
                onContinueWithError={(error) => {
                  setInput(`刚才 Agent 运行失败，错误如下：\n${error}\n\n请基于这个错误继续处理。`);
                }}
                input={input}
                onInputChange={setInput}
                showConversations={showConversations}
                onToggleConversations={() => setShowConversations((v) => !v)}
              />
            </div>
          </div>
        )}

        {activeView === "overview" && (
          <OverviewPanel
            overview={overview.overview}
            loading={overview.loading}
            saving={overview.saving}
            error={overview.error}
            onRefresh={overview.refresh}
            onSave={overview.save}
            onOpenFile={handleOpenFile}
          />
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

        {activeView === "vector" && (
          <VectorPanel
            status={vectorIndex.status}
            results={vectorIndex.results}
            loading={vectorIndex.loading}
            rebuilding={vectorIndex.rebuilding}
            searching={vectorIndex.searching}
            error={vectorIndex.error}
            onRefresh={vectorIndex.refresh}
            onRebuild={vectorIndex.rebuild}
            onSearch={vectorIndex.search}
            onOpenFile={handleOpenFile}
          />
        )}

        {activeToolView && renderRegisteredWorkspaceView(activeToolView.view_id as ViewId, {
          outline: {
            ...outline,
            save: async (title, items) => {
              const result = await outline.save(title, items);
              void overview.refresh();
              void vectorIndex.refresh();
              return result;
            },
            importMarkdown: async () => {
              const result = await outline.importMarkdown();
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
          },
          chapters: {
            ...chapters,
            saveDocument: async (path, content) => {
              await chapters.saveDocument(path, content);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
            },
            saveMetadata: async (path, metadata) => {
              await chapters.saveMetadata(path, metadata);
              void overview.refresh();
            },
          },
          foreshadows: {
            ...foreshadows,
            save: async (items) => {
              const result = await foreshadows.save(items);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
          },
          characters,
          worldview: {
            ...worldview,
            saveDocument: async (path, content) => {
              const result = await worldview.saveDocument(path, content);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
            renameDocument: async (oldPath, newPath) => {
              const result = await worldview.renameDocument(oldPath, newPath);
              if (selectedFilePath === oldPath && result?.path) {
                setSelectedFilePath(result.path);
              }
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
            deleteDocument: async (path) => {
              const deleted = await worldview.deleteDocument(path);
              if (deleted === false) return false;
              if (selectedFilePath === path) {
                setSelectedFilePath(null);
                setSelectedFileContent("");
              }
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return deleted;
            },
          },
          vector: {
            status: vectorIndex.status,
            results: vectorIndex.results,
            searching: vectorIndex.searching,
            rebuilding: vectorIndex.rebuilding,
            error: vectorIndex.error,
            search: vectorIndex.search,
            rebuild: vectorIndex.rebuild,
          },
          tools: tools.tools,
          openTool: (tool, initialParams) => { setSelectedTool(tool); setSelectedToolRun(null); setToolInitialParams(initialParams ?? null); },
          openFile: handleOpenFile,
        })}

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
            onCopy={presets.copy}
            onUpdate={presets.update}
            onListModels={presets.listModels}
            onDelete={presets.remove}
            isBuiltin={presets.isBuiltin}
            tools={tools.tools}
          />
        )}

        {activeView === "tools" && (
          <ToolsPanel
            tools={tools.tools}
            runs={tools.runs}
            loading={tools.loading}
            error={tools.error}
            onRefresh={tools.refresh}
            onSelect={(tool) => { setSelectedTool(tool); setSelectedToolRun(null); setToolInitialParams(null); }}
            onSelectRun={(run) => { setSelectedTool(null); setSelectedToolRun(run); setToolInitialParams(null); tools.clearResult(); }}
            onReuseRun={(run) => {
              const tool = tools.tools.find((item) => item.name === run.tool_name);
              if (!tool) return;
              setSelectedTool(tool);
              setSelectedToolRun(null);
              setToolInitialParams(run.params);
              tools.clearResult();
            }}
          />
        )}
      </main>

      <ToolDrawer
        tool={selectedTool}
        run={selectedToolRun ?? tools.result}
        initialParams={toolInitialParams}
        error={tools.error}
        running={tools.running}
        presets={presets.presets}
        activePresetId={presets.activeId}
        onClose={() => { setSelectedTool(null); setSelectedToolRun(null); setToolInitialParams(null); tools.clearResult(); }}
        onExecute={async (name, params) => {
          const result = await tools.execute(name, params);
          if (name === "write_chapter" || name === "edit_chapter") {
            void overview.refresh();
            void chapters.refresh();
            void fileTree.refresh();
            void vectorIndex.refresh();
          }
          if (name === "outline_generate") void outline.refresh();
          if (name === "foreshadow_manage") void foreshadows.refresh();
          if (name === "create_character") void characters.refresh();
          if (name === "update_worldview") void worldview.refresh();
          if (name === "update_worldview" || name === "create_character" || name === "outline_generate" || name === "foreshadow_manage") void vectorIndex.refresh();
          return result;
        }}
        onInvoke={async (name, params, presetId) => {
          const result = await tools.invoke(name, params, presetId);
          if (name === "write_chapter" || name === "edit_chapter") {
            void overview.refresh();
            void chapters.refresh();
            void fileTree.refresh();
            void vectorIndex.refresh();
          }
          if (name === "outline_generate") void outline.refresh();
          if (name === "foreshadow_manage") void foreshadows.refresh();
          if (name === "create_character") void characters.refresh();
          if (name === "update_worldview") void worldview.refresh();
          if (name === "update_worldview" || name === "create_character" || name === "outline_generate" || name === "foreshadow_manage") void vectorIndex.refresh();
          return result;
        }}
        onUpdateDefaultPreset={async (name, presetId) => {
          await tools.updateDefaultPreset(name, presetId);
          setSelectedTool((current) => current?.name === name ? { ...current, default_preset_id: presetId } : current);
        }}
      />
    </div>
  );
}

export default App;
