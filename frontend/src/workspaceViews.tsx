import type { ReactNode } from "react";
import ChapterPanel from "./components/ChapterPanel";
import CharacterPanel from "./components/CharacterPanel";
import OutlinePanel from "./components/OutlinePanel";
import WorldviewPanel from "./components/WorldviewPanel";
import type {
  OutlineItem,
  StoryChapterMetadataUpdate,
  StoryChapters,
  StoryCharacters,
  StoryOutline,
  StoryWorldview,
  ToolDescriptor,
  VectorIndexStatus,
  VectorSearchResult,
  ViewId,
} from "./types";

export interface WorkspaceViewContext {
  outline: {
    outline: StoryOutline | null;
    loading: boolean;
    error: string;
    refresh: () => void;
    save: (title: string, items: OutlineItem[]) => void | Promise<unknown>;
  };
  chapters: {
    chapters: StoryChapters | null;
    loading: boolean;
    saving: boolean;
    error: string;
    refresh: () => void;
    saveDocument: (path: string, content: string) => Promise<unknown>;
    saveMetadata: (path: string, metadata: StoryChapterMetadataUpdate) => Promise<unknown>;
  };
  vector: {
    status: VectorIndexStatus | null;
    results: VectorSearchResult[];
    searching: boolean;
    rebuilding: boolean;
    error: string;
    search: (query: string, collections: string[], topK: number) => void | Promise<unknown>;
    rebuild: () => void | Promise<unknown>;
  };
  characters: {
    characters: StoryCharacters | null;
    loading: boolean;
    error: string;
    refresh: () => void;
  };
  worldview: {
    worldview: StoryWorldview | null;
    loading: boolean;
    saving: boolean;
    error: string;
    refresh: () => void;
    saveDocument: (path: string, content: string) => void | Promise<unknown>;
  };
  tools: ToolDescriptor[];
  openTool: (tool: ToolDescriptor, initialParams?: Record<string, unknown>) => void;
  openFile: (path: string) => void;
}

export interface WorkspaceViewDefinition {
  viewId: ViewId;
  render: (context: WorkspaceViewContext) => ReactNode;
}

export const WORKSPACE_VIEW_REGISTRY: WorkspaceViewDefinition[] = [
  {
    viewId: "outline",
    render: ({ outline, tools, openTool }) => (
      <OutlinePanel
        outline={outline.outline}
        loading={outline.loading}
        error={outline.error}
        tools={tools}
        onRefresh={outline.refresh}
        onSave={outline.save}
        onOpenTool={openTool}
      />
    ),
  },
  {
    viewId: "chapters",
    render: ({ chapters, vector, tools, openTool, openFile }) => (
      <ChapterPanel
        chapters={chapters.chapters}
        loading={chapters.loading}
        saving={chapters.saving}
        error={chapters.error}
        vectorStatus={vector.status}
        vectorResults={vector.results}
        vectorSearching={vector.searching}
        vectorRebuilding={vector.rebuilding}
        vectorError={vector.error}
        tools={tools}
        onRefresh={chapters.refresh}
        onSaveDocument={chapters.saveDocument}
        onSaveMetadata={chapters.saveMetadata}
        onVectorSearch={vector.search}
        onVectorRebuild={vector.rebuild}
        onOpenTool={openTool}
        onOpenFile={openFile}
      />
    ),
  },
  {
    viewId: "characters",
    render: ({ characters, tools, openTool }) => (
      <CharacterPanel
        characters={characters.characters}
        loading={characters.loading}
        error={characters.error}
        tools={tools}
        onRefresh={characters.refresh}
        onOpenTool={openTool}
      />
    ),
  },
  {
    viewId: "worldview",
    render: ({ worldview, tools, openTool }) => (
      <WorldviewPanel
        worldview={worldview.worldview}
        loading={worldview.loading}
        saving={worldview.saving}
        error={worldview.error}
        tools={tools}
        onRefresh={worldview.refresh}
        onSaveDocument={worldview.saveDocument}
        onOpenTool={openTool}
      />
    ),
  },
];

export function supportedWorkspaceViewIds() {
  return new Set(WORKSPACE_VIEW_REGISTRY.map((view) => view.viewId));
}

export function renderRegisteredWorkspaceView(viewId: ViewId, context: WorkspaceViewContext) {
  return WORKSPACE_VIEW_REGISTRY.find((view) => view.viewId === viewId)?.render(context) ?? null;
}
