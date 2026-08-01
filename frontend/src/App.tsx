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
import WorkflowPanel from "./components/WorkflowPanel";
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
import { usePromptPacks } from "./hooks/usePromptPacks";
import { useSystemRules } from "./hooks/useSystemRules";
import { useTools } from "./hooks/useTools";
import { useVectorIndex } from "./hooks/useVectorIndex";
import { useWorkflows } from "./hooks/useWorkflows";
import { useWorldview } from "./hooks/useWorldview";
import type { AgentEvent, ConversationMessage, ToolDescriptor, ToolRunRecord, ToolWorkspaceView, ViewId } from "./types";
import type { WorkspaceChangeNotice } from "./components/AiRender/types";
import { renderRegisteredWorkspaceView, supportedWorkspaceViewIds } from "./workspaceViews";
import "./style.css";

function conversationMessagesToEvents(messages: ConversationMessage[]): AgentEvent[] {
  return messages.map((message) => ({
    type: message.type,
    content: message.content,
    sender: message.role,
    ui_hint: message.ui_hint ?? undefined,
    metadata: message.metadata,
  }));
}

function encodeProjectFilePath(path: string) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function isTempTextPath(path: string) {
  return [".md", ".txt", ".json", ".yaml", ".yml", ".csv"].some((ext) => path.toLowerCase().endsWith(ext));
}

function App() {
  const {
    project,
    projects,
    loadingProjects,
    projectError,
    setProject,
    selectFolder,
    setProjectPath,
    createProject,
    importProject,
    exportProject,
    renameProject,
    deleteProject,
    refreshProjects,
  } = useProject();
  const [activeView, setActiveView] = useState<ViewId>("overview");
  const [focusedCharacterId, setFocusedCharacterId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [selectedTool, setSelectedTool] = useState<ToolDescriptor | null>(null);
  const [selectedToolRun, setSelectedToolRun] = useState<ToolRunRecord | null>(null);
  const [toolInitialParams, setToolInitialParams] = useState<Record<string, unknown> | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedFileContent, setSelectedFileContent] = useState("");
  const [fileSaving, setFileSaving] = useState(false);
  const [showConversations, setShowConversations] = useState(false);
  const projectInitRef = useRef<string | null>(null);
  const onboardingImportInputRef = useRef<HTMLInputElement | null>(null);

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
  const promptPacks = usePromptPacks(project?.path ?? null);
  const systemRules = useSystemRules(project?.path ?? null);
  const tools = useTools(project?.path ?? null, presets.activeId);
  const vectorIndex = useVectorIndex(project?.path ?? null);
  const workflows = useWorkflows(project?.path ?? null);
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

  const { connected, events, historyVersion, activeRun, send, interrupt, retryRun, setPresetId, setHistory, clearEvents } =
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
      `/projects/files/${encodeProjectFilePath(path)}?project_path=${encodeURIComponent(project.path)}`,
    );
    setSelectedFileContent(response.content);
    setActiveView("files");
  }, [project?.path]);

  const handleOpenCharacter = useCallback((characterId: string) => {
    setFocusedCharacterId(characterId);
    setActiveView("characters");
  }, []);

  const handleAgentWorkspaceChanged = useCallback(async (notice: WorkspaceChangeNotice) => {
    if (!project?.path) return;
    const selectedChange = selectedFilePath
      ? notice.changes.find((change) => change.path === selectedFilePath)
      : undefined;

    await Promise.allSettled([
      fileTree.refresh(),
      overview.refresh(),
      chapters.refresh(),
      outline.refresh(),
      foreshadows.refresh(),
      characters.refresh(),
      worldview.refresh(),
      vectorIndex.refresh(),
    ]);

    if (!selectedChange || !selectedFilePath) return;
    if (selectedChange.operation === "delete") {
      setSelectedFilePath(null);
      setSelectedFileContent("");
      return;
    }
    try {
      const response = await api.get<{ path: string; content: string }>(
        `/projects/files/${encodeProjectFilePath(selectedFilePath)}?project_path=${encodeURIComponent(project.path)}`,
      );
      setSelectedFileContent(response.content);
    } catch {
      // The file tree refresh already reflects the authoritative state.
    }
  }, [
    chapters.refresh,
    characters.refresh,
    fileTree.refresh,
    foreshadows.refresh,
    outline.refresh,
    overview.refresh,
    project?.path,
    selectedFilePath,
    vectorIndex.refresh,
    worldview.refresh,
  ]);

  const handleSaveFile = useCallback(async () => {
    if (!project?.path || !selectedFilePath) return;
    setFileSaving(true);
    try {
      await api.put(`/projects/files/${encodeProjectFilePath(selectedFilePath)}?project_path=${encodeURIComponent(project.path)}`, {
        content: selectedFileContent,
      });
      await fileTree.refresh();
      void vectorIndex.refresh();
    } finally {
      setFileSaving(false);
    }
  }, [fileTree.refresh, project?.path, selectedFileContent, selectedFilePath, vectorIndex.refresh]);

  const normalizeTempInputPath = useCallback((value: string, baseDir = "temp/notes") => {
    const trimmed = value.trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!trimmed) return "";
    const path = trimmed.startsWith("temp/") ? trimmed : `${baseDir.replace(/\/+$/, "")}/${trimmed}`;
    if (path.includes("\0") || path.split("/").some((part) => !part || part === "." || part === "..")) return "";
    if (path === "temp/.aisync-temp.json" || !isTempTextPath(path)) return "";
    return path;
  }, []);

  const handleCreateTempFile = useCallback(async (dirPath: string) => {
    if (!project?.path) return;
    const filename = window.prompt("新建自由区文本文件", "notes.md");
    if (filename === null) return;
    const path = normalizeTempInputPath(filename, dirPath);
    if (!path) {
      window.alert("请输入 temp/ 下的有效文本文件名：.md、.txt、.json、.yaml、.yml 或 .csv。");
      return;
    }
    try {
      await api.put(`/projects/files/${encodeProjectFilePath(path)}?project_path=${encodeURIComponent(project.path)}`, {
        content: "",
      });
      await fileTree.refresh();
      await handleOpenFile(path);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "新建文件失败");
    }
  }, [fileTree.refresh, handleOpenFile, normalizeTempInputPath, project?.path]);

  const handleRenameTempFile = useCallback(async (oldPath: string) => {
    if (!project?.path) return;
    const newValue = window.prompt("重命名自由区文件", oldPath);
    if (newValue === null) return;
    const newPath = normalizeTempInputPath(newValue, oldPath.split("/").slice(0, -1).join("/") || "temp/notes");
    if (!newPath) {
      window.alert("请输入 temp/ 下的有效文本文件目标路径。");
      return;
    }
    try {
      await api.post<{ path: string }>("/projects/files/move", {
        project_path: project.path,
        old_path: oldPath,
        new_path: newPath,
      });
      if (selectedFilePath === oldPath) {
        setSelectedFilePath(newPath);
      }
      await fileTree.refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "重命名失败");
    }
  }, [fileTree.refresh, normalizeTempInputPath, project?.path, selectedFilePath]);

  const handleDeleteTempFile = useCallback(async (path: string) => {
    if (!project?.path) return;
    if (!window.confirm(`确定删除自由区文件？\n${path}`)) return;
    try {
      await api.del(`/projects/files/${encodeProjectFilePath(path)}?project_path=${encodeURIComponent(project.path)}`);
      if (selectedFilePath === path) {
        setSelectedFilePath(null);
        setSelectedFileContent("");
      }
      await fileTree.refresh();
      void vectorIndex.refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "删除失败");
    }
  }, [fileTree.refresh, project?.path, selectedFilePath, vectorIndex.refresh]);

  const handleDeleteDirectory = useCallback(async (path: string) => {
    if (!project?.path) return;
    if (!window.confirm(`确定递归删除目录及其中的项目文件？\n${path}\n\n项目内部运行文件不会被删除。`)) return;
    try {
      await api.del(`/projects/directories/${encodeProjectFilePath(path)}?project_path=${encodeURIComponent(project.path)}`);
      if (selectedFilePath === path || selectedFilePath?.startsWith(`${path}/`)) {
        setSelectedFilePath(null);
        setSelectedFileContent("");
      }
      await fileTree.refresh();
      void vectorIndex.refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "删除目录失败");
    }
  }, [fileTree.refresh, project?.path, selectedFilePath, vectorIndex.refresh]);

  const handleCreateChapterDraftWorkflow = useCallback(async () => {
    await workflows.createFromTemplate("chapter_draft_safe", {
      title: "章节草稿工作流",
      input_summary: "章节草稿最小流程：先规划，再确认，再写作，最后输出到 temp/drafts。",
    });
  }, [workflows]);

  return (
    <div className="app-shell">
      <Sidebar
        projectName={project?.name ?? "未选择"}
        projectPath={project?.path ?? ""}
        projects={projects}
        projectsLoading={loadingProjects}
        projectError={projectError}
        connected={connected}
        activeView={activeView}
        toolViews={toolViews}
        onViewChange={setActiveView}
        onSelectFolder={() => void selectFolder()}
        onSetProjectPath={(path) => void setProjectPath(path)}
        onSelectProject={(path) => {
          const next = projects.find((item) => item.path === path);
          if (next) setProject(next);
        }}
        onCreateProject={() => void createProject()}
        onImportProject={(file) => void importProject(file)}
        onExportProject={() => void exportProject()}
        onRenameProject={() => void renameProject()}
        onDeleteProject={() => void deleteProject()}
        onRefreshProjects={() => void refreshProjects()}
      />

      <main className="main-content">
        {!project?.path && (
          <div className="project-onboarding">
            <div className="project-onboarding-panel">
              <div className="project-onboarding-mark">A</div>
              <h2>选择一个小说项目</h2>
              <p>项目会保存在 AiSync 的项目库中，也可以从备份 zip 导入；外部文件夹适合接管旧项目或临时测试。</p>
              {projectError && <div className="project-onboarding-error">{projectError}</div>}
              <div className="project-onboarding-actions">
                <button className="btn-primary" onClick={() => void createProject()} type="button">
                  新建项目
                </button>
                <button className="btn-secondary" onClick={() => onboardingImportInputRef.current?.click()} type="button">
                  导入项目
                </button>
                <button className="btn-secondary" onClick={() => void selectFolder()} type="button">
                  打开外部文件夹
                </button>
                <button className="btn-ghost" onClick={() => void refreshProjects()} type="button">
                  刷新项目库
                </button>
              </div>
              {loadingProjects && <p className="project-onboarding-muted">正在读取项目库...</p>}
              <input
                ref={onboardingImportInputRef}
                className="project-onboarding-file"
                type="file"
                accept=".zip,.aisync.zip,application/zip"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void importProject(file);
                }}
              />
            </div>
          </div>
        )}

        {project?.path && activeView === "chat" && (
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
                onRetryRun={retryRun}
                onContinueWithError={(error) => {
                  setInput(`刚才 Agent 运行失败，错误如下：\n${error}\n\n请基于这个错误继续处理。`);
                }}
                onWorkspaceChanged={handleAgentWorkspaceChanged}
                input={input}
                onInputChange={setInput}
                showConversations={showConversations}
                onToggleConversations={() => setShowConversations((v) => !v)}
              />
            </div>
          </div>
        )}

        {project?.path && activeView === "overview" && (
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

        {project?.path && activeView === "files" && (
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
              <FileTree
                tree={fileTree.tree}
                activePath={selectedFilePath}
                onOpenFile={handleOpenFile}
                onCreateTempFile={handleCreateTempFile}
                onDeleteDirectory={handleDeleteDirectory}
                onRenameTempFile={handleRenameTempFile}
                onDeleteTempFile={handleDeleteTempFile}
              />
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

        {project?.path && activeView === "vector" && (
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

        {project?.path && activeView === "workflows" && (
          <WorkflowPanel
            runs={workflows.runs}
            activeRun={workflows.activeRun}
            loading={workflows.loading}
            error={workflows.error}
            onRefresh={() => void workflows.refresh()}
            onCreateChapterDraft={handleCreateChapterDraftWorkflow}
            onCreateChapterBatch={workflows.createChapterBatch}
            onCreateFromTemplate={workflows.createFromTemplate}
            onCreateCustom={workflows.create}
            onSelectRun={workflows.selectRun}
            onUpdateStatus={workflows.updateStatus}
            onUpdateRun={workflows.updateRun}
            onUpdateStep={workflows.updateStep}
            onAddStep={workflows.addStep}
            onDeleteStep={workflows.deleteStep}
            onResetStep={workflows.resetStep}
            onSkipStep={workflows.skipStep}
            onDeleteRun={workflows.remove}
            onRunNext={workflows.runNext}
            onRunContinuous={workflows.runContinuous}
            onPause={workflows.pause}
            onConfirm={workflows.confirm}
            executingRunId={workflows.executingRunId}
            continuousRunId={workflows.continuousRunId}
            presets={presets.presets}
            templates={workflows.templates}
            promptPacks={promptPacks.packs}
          />
        )}

        {project?.path && activeToolView && renderRegisteredWorkspaceView(activeToolView.view_id as ViewId, {
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
            saveSource: async (content) => {
              const result = await outline.saveSource(content);
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
            confirmVerification: async (foreshadowId) => {
              const result = await foreshadows.confirmVerification(foreshadowId);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
          },
          characters: {
            ...characters,
            focusedCharacterId,
            save: async (character) => {
              const result = await characters.save(character);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
            archive: async (slug, reason) => {
              const result = await characters.archive(slug, reason);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
            restore: async (archiveId) => {
              const result = await characters.restore(archiveId);
              void overview.refresh();
              void fileTree.refresh();
              void vectorIndex.refresh();
              return result;
            },
          },
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
          openCharacter: handleOpenCharacter,
        })}

        {project?.path && activeView === "settings" && presets.loading && (
          <div className="view-status view-status--loading">加载预设中…</div>
        )}
        {project?.path && activeView === "settings" && presets.error && (
          <div className="view-status view-status--error">{presets.error}</div>
        )}
        {project?.path && activeView === "settings" && !presets.loading && !presets.error && (
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
            promptPacks={promptPacks}
            systemRules={systemRules}
          />
        )}

        {project?.path && activeView === "tools" && (
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
