/* ── 视图类型 ── */

export type ViewId = "overview" | "chat" | "chapters" | "outline" | "characters" | "worldview" | "vector" | "tools" | "settings" | "files";

export interface ProjectInfo {
  name: string;
  path: string;
}

/* ── Agent 事件 ── */

export interface AgentEvent {
  type: string;
  content?: string;
  ui_hint?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  memory?: {
    summary?: boolean;
    recent_messages?: number;
    summary_pending?: boolean;
    summary_quality?: {
      score?: number;
      status?: string;
      issues?: string[];
    } | null;
  };
  tool?: {
    name?: string;
    params?: Record<string, unknown>;
    duration_ms?: number;
    error?: string;
  };
  sender?: "user" | "agent";
  conversation_id?: string;
}

/* ── 对话历史 ── */

export type ConversationStatus = "idle" | "running" | "interrupted" | "failed" | "completed";

export interface ConversationMessage {
  role: "user" | "agent";
  content: string;
  type: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: ConversationStatus;
  last_error: string | null;
  running_since: string | null;
  messages: ConversationMessage[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  status: ConversationStatus;
  last_error: string | null;
  running_since: string | null;
}

/* ── 故事对象 ── */

export interface OutlineItem {
  index?: number;
  title?: string;
  summary?: string;
  raw?: string;
  [key: string]: unknown;
}

export interface StoryOutline {
  source: string | null;
  format: "json" | "markdown" | "empty" | string;
  title: string;
  items: OutlineItem[];
  content?: string;
  raw?: unknown;
}

export interface StoryCharacter {
  slug: string;
  name: string;
  role: string;
  summary: string;
  profile: string;
  profile_path: string;
  metadata_path: string;
}

export interface StoryCharacters {
  source: string;
  items: StoryCharacter[];
}

export interface WorldviewDocument {
  path: string;
  title: string;
  content: string;
  summary: string;
}

export interface StoryWorldview {
  source: string;
  items: WorldviewDocument[];
}

export interface StoryChapter {
  path: string;
  title: string;
  content: string;
  summary: string;
  characters: number;
  status: string;
  target_characters: number;
  revision: number;
}

export interface StoryChapterMetadataUpdate {
  status: string;
  summary: string;
  target_characters: number;
  revision: number;
}

export interface StoryChapters {
  source: string;
  items: StoryChapter[];
  total_characters: number;
}

export interface ProjectOverviewChapter {
  path: string;
  title: string;
  characters: number;
}

export interface ProjectOverviewStats {
  completed_chapters: number;
  total_characters: number;
  characters: number;
  world_documents: number;
  outline_items: number;
  chapter_progress: number;
  character_progress: number;
}

export interface ProjectOverview {
  name: string;
  status: string;
  synopsis: string;
  goal: string;
  target_chapters: number;
  target_characters: number;
  path: string;
  stats: ProjectOverviewStats;
  chapters: ProjectOverviewChapter[];
  world_documents: string[];
}

export interface ProjectOverviewUpdate {
  name: string;
  status: string;
  synopsis: string;
  goal: string;
  target_chapters: number;
  target_characters: number;
}

export interface VectorIndexStatus {
  status: "missing" | "invalid" | "stale" | "ready" | string;
  indexed: boolean;
  stale: boolean;
  files: number;
  indexed_files?: number;
  chunks: number;
  collections: Record<string, number>;
  embedding_model?: string | null;
  embedding_configured?: boolean;
  backend?: "local" | "chroma" | string;
  chroma_available?: boolean;
  index_path: string;
}

export interface VectorSearchResult {
  path: string;
  collection: string;
  content: string;
  score: number;
  chunk_id: string;
}

/* ── 工具 ── */

export interface ToolFileAccess {
  read: string[];
  write: string[];
  generate: string[];
}

export interface ToolPresentation {
  type: string;
  description?: string | null;
}

export interface ToolWorkspaceView {
  view_id: string;
  label: string;
  marker: string;
}

export interface ToolSummary {
  name: string;
  description: string;
  has_frontend_ui: boolean;
  input_schema: Record<string, unknown>;
  ui_schema: Record<string, unknown> | null;
  default_preset_id: string | null;
  default_agent: string | null;
  file_access: ToolFileAccess;
  presentation: ToolPresentation | null;
  workspace_view?: ToolWorkspaceView | null;
}

/* ── 预设 ── */

export interface LLMParams {
  provider: "anthropic" | "openai" | "custom";
  api_key: string | null;
  api_key_env: string;
  api_base: string | null;
  model_name: string;
  max_tokens: number;
  effort: string;
  enable_thinking: boolean;
  prompt_cache: boolean;
}

export interface AgentBehavior {
  system_prompt: string | null;
  enabled_tools: string[] | null;
}

export interface Preset {
  id: string;
  name: string;
  llm: LLMParams;
  behavior: AgentBehavior;
  created_at: string | null;
  updated_at: string | null;
}

export interface PresetCreate {
  name: string;
  llm?: Partial<LLMParams>;
  behavior?: Partial<AgentBehavior>;
}

export interface PresetCopy {
  name?: string | null;
}

export interface PresetUpdate {
  name?: string;
  llm?: Partial<LLMParams>;
  behavior?: Partial<AgentBehavior>;
}

export interface ModelListResponse {
  models: string[];
}

/* ── 工具执行结果 ── */

export interface ToolResult {
  content: string;
  ui_hint?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
}

export interface ToolRunRecord {
  run_id: string;
  tool_name: string;
  mode: "execute" | "invoke";
  status: "completed" | "failed";
  started_at: string;
  finished_at: string;
  file_access: ToolFileAccess;
  params: Record<string, unknown>;
  result: ToolResult | null;
  error: string | null;
}

/** 工具完整描述（含 schema，API 返回） */
export type ToolDescriptor = ToolSummary;
