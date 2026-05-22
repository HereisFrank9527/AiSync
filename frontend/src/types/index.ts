/* ── 视图类型 ── */

export type ViewId = "overview" | "chat" | "chapters" | "outline" | "foreshadows" | "characters" | "worldview" | "vector" | "workflows" | "tools" | "settings" | "files";

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
    summary_updated_at?: string | null;
    summary_chars?: number;
    recent_window?: number;
    old_message_count?: number;
    total_message_count?: number;
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
  run?: AgentRunRecord;
}

export type AgentRunStatus = "running" | "completed" | "failed" | "interrupted";

export interface AgentRunRecord {
  run_id: string;
  conversation_id: string;
  status: AgentRunStatus;
  phase: string;
  phase_label: string;
  started_at: string;
  updated_at: string;
  finished_at: string | null;
  preset_id: string | null;
  enabled_tools: string[] | null;
  input_preview: string;
  error: string | null;
  prompt_audit?: {
    system_prompt?: {
      source?: string;
      chars?: number;
    };
    user_input?: {
      chars?: number;
    };
    memory?: {
      summary?: boolean;
      summary_chars?: number;
      recent_messages?: number;
    };
    vector_context?: {
      count?: number;
      paths?: string[];
    };
    foreshadow_context?: {
      included?: boolean;
      chars?: number;
    };
    prompt_packs?: {
      stage?: string;
      count?: number;
      names?: string[];
    };
    tools?: {
      mode?: string;
      count?: number;
      names?: string[];
    };
  };
  tool_calls: Array<{
    name?: string;
    status?: string;
    duration_ms?: number | null;
    error?: string | null;
    at?: string;
  }>;
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
  id?: string;
  index?: number;
  title?: string;
  summary?: string;
  status?: string;
  raw?: string;
  [key: string]: unknown;
}

export interface StoryOutline {
  source: string | null;
  format: "json" | "markdown" | "empty" | string;
  title: string;
  items: OutlineItem[];
  content?: string;
  importable_items?: OutlineItem[];
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
  outline_id: string;
}

export interface StoryChapterMetadataUpdate {
  status: string;
  summary: string;
  target_characters: number;
  revision: number;
  outline_id: string;
}

export interface StoryChapters {
  source: string;
  items: StoryChapter[];
  total_characters: number;
}

export interface ForeshadowItem {
  id: string;
  title: string;
  summary: string;
  status: string;
  importance: string;
  plant_chapter: string;
  payoff_chapter: string;
  outline_ids: string[];
  related_files: string[];
  tags: string[];
  notes: string;
}

export interface StoryForeshadows {
  source: string;
  items: ForeshadowItem[];
  stats: {
    total: number;
    paid_off: number;
    open: number;
  };
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
  completed_outline_items: number;
  foreshadow_items: number;
  paid_off_foreshadow_items: number;
  chapter_progress: number;
  character_progress: number;
  outline_progress: number;
  foreshadow_progress: number;
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
  error?: string;
}

export type PromptPackCategory = "style" | "writing" | "planning" | "revision" | "check" | "special" | "custom";
export type PromptPackStage = "chat" | "chapter_plan" | "chapter_draft" | "revision" | "check" | "special";
export type PromptPackScope = "global" | "project";

export interface PromptPack {
  id: string;
  name: string;
  category: PromptPackCategory;
  scope: PromptPackScope;
  stages: PromptPackStage[];
  content: string;
  enabled: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface PromptPackCreate {
  name: string;
  category?: PromptPackCategory;
  scope?: PromptPackScope;
  stages?: PromptPackStage[];
  content?: string;
  enabled?: boolean;
  description?: string;
}

export type PromptPackUpdate = Partial<PromptPackCreate>;

export interface ProjectPromptPackSettings {
  mode: "global" | "project";
  enabled_pack_ids: string[];
}

/* ── 工作流 ── */

export type WorkflowRunStatus = "draft" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type WorkflowStepStatus = "pending" | "running" | "waiting_user" | "completed" | "failed" | "skipped";
export type WorkflowStepKind = "plan" | "context" | "draft" | "revise" | "check" | "write_file" | "user_confirm" | "custom";

export interface WorkflowStepRecord {
  step_id: string;
  name: string;
  kind: WorkflowStepKind;
  status: WorkflowStepStatus;
  preset_id: string | null;
  prompt_pack_ids: string[];
  context_pack_ids: string[];
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  output_path: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface WorkflowRunRecord {
  run_id: string;
  workflow_type: string;
  title: string;
  status: WorkflowRunStatus;
  current_step_id: string | null;
  conversation_id: string | null;
  agent_run_id: string | null;
  input_summary: string;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  steps: WorkflowStepRecord[];
  metadata: Record<string, unknown>;
}

export interface WorkflowRunCreate {
  workflow_type?: string;
  title: string;
  input_summary?: string;
  conversation_id?: string | null;
  agent_run_id?: string | null;
  steps?: Array<Partial<WorkflowStepRecord> & { name: string }>;
  metadata?: Record<string, unknown>;
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
