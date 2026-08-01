/* ── 视图类型 ── */

export type ViewId = "overview" | "chat" | "chapters" | "outline" | "foreshadows" | "characters" | "worldview" | "vector" | "workflows" | "tools" | "settings" | "files";

export interface ProjectInfo {
  id?: string;
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
    call_id?: string;
    name?: string;
    params?: Record<string, unknown>;
    duration_ms?: number;
    error?: string;
  };
  sender?: "user" | "agent";
  conversation_id?: string;
  run?: AgentRunRecord;
}

export interface WebSource {
  url: string;
  title?: string;
  snippet?: string;
  provider?: string;
}

export type AgentRunStatus = "running" | "completed" | "failed" | "interrupted" | "waiting_user";

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
  retry_of_run_id?: string | null;
  retry_mode?: "restart" | "finalize" | null;
  input_preview: string;
  error: string | null;
  draft_content: string;
  draft_version: number;
  draft_updated_at: string | null;
  prompt_audit?: {
    system_prompt?: {
      source?: string;
      base_source?: string;
      chars?: number;
      project_rules?: {
        mode?: "default" | "project" | string;
        included?: boolean;
        chars?: number;
        updated_at?: string | null;
      };
    };
    user_input?: {
      chars?: number;
    };
    memory?: {
      summary?: boolean;
      summary_chars?: number;
      recent_messages?: number;
      injected_recent_messages?: number;
    };
    context_window?: {
      mode?: "economy" | "standard" | "long" | "maximum" | string;
      label?: string;
      recent_messages?: number;
      memory_chars?: number;
      single_message_chars?: number;
      vector_top_k?: number;
      vector_item_chars?: number;
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
    prompt_cache?: {
      enabled?: boolean;
      layout?: string;
      stable_prefix_messages?: number;
      dynamic_sections_after_prefix?: string[];
    };
    tool_continuation?: {
      strategy?: string;
      recent_history_messages?: number;
      stream?: boolean;
      fallback?: string;
    };
    usage?: {
      model_request_attempts?: number;
      model_requests?: number;
      tool_calls?: number;
      duplicate_tool_calls?: number;
      failed_tool_calls?: number;
      coalesced_change_proposals?: number;
      applied_change_sets?: Array<{
        changeset_id?: string;
        status?: "verified" | "review" | string;
        verified?: number;
        total?: number;
        paths?: string[];
      }>;
      safe_finalize_attempts?: number;
      consecutive_no_progress_batches?: number;
      termination_reason?: string;
      output_truncated?: boolean;
      file_change_approval_timeout_seconds?: number;
      change_approvals?: Array<{
        changeset_id?: string;
        decision?: "applied" | "discarded" | string;
        iteration?: number;
      }>;
      input_tokens?: number;
      output_tokens?: number;
      total_tokens?: number;
      estimated_input_tokens?: number;
      estimated_output_tokens?: number;
      estimated_total_tokens?: number;
      search_credits?: number;
      search_calls?: Array<{
        tool?: string;
        provider?: string;
        credits?: number;
        request_id?: string;
        response_time?: number;
        search_depth?: string;
      }>;
      request_timeout_seconds?: number;
      request_timeout_mode?: "idle" | "total" | string;
      request_stream_requested?: boolean;
      request_stream_callback?: boolean;
      last_request_phase?: string;
      last_request_message_count?: number;
      last_request_tool_count?: number;
      last_request_estimated_input_tokens?: number;
      last_error_category?: string;
      last_error_message?: string;
      tool_batches?: Array<{
        iteration?: number;
        count?: number;
        duplicates?: number;
        failed?: number;
        tools?: Array<{
          name?: string;
          status?: string;
          content_chars?: number;
          ui_type?: string;
          preset_id?: string;
          mode?: string;
        }>;
      }>;
      llm_calls?: Array<{
        index?: number;
        phase?: string;
        iteration?: number | null;
        provider?: string;
        model?: string;
        stream_requested?: boolean;
        stream_callback?: boolean;
        timeout_seconds?: number;
        message_count?: number;
        tool_count?: number;
        has_tool_result?: boolean;
        estimated_input_tokens?: number;
        status?: string;
        started_at?: string;
        finished_at?: string;
        tool_calls_returned?: number;
        output_chars?: number;
        stop_reason?: string | null;
        error_category?: string;
        error_message?: string;
      }>;
    };
  };
  tool_calls: Array<{
    call_id?: string;
    name?: string;
    status?: string;
    duration_ms?: number | null;
    error?: string | null;
    preset_id?: string | null;
    mode?: string | null;
    params?: Record<string, unknown>;
    at?: string;
    finished_at?: string;
  }>;
}

/* ── 对话历史 ── */

export type ConversationStatus = "idle" | "running" | "interrupted" | "failed" | "completed" | "waiting_user";

export interface ConversationMessage {
  role: "user" | "agent";
  content: string;
  type: string;
  created_at: string;
  ui_hint?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
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
  character_ids?: string[];
  raw?: string;
  [key: string]: unknown;
}

export type OutlineNodeKind = "volume" | "chapter" | "section" | "markdown" | string;

export interface OutlineNode {
  id: string;
  kind: OutlineNodeKind;
  level: number;
  parent_id?: string | null;
  title: string;
  heading?: string;
  body?: string;
  raw_markdown?: string;
  index?: number;
  chapter_number?: string;
  summary?: string;
  status?: string;
  character_ids?: string[];
  source_start_line?: number;
  source_end_line?: number;
}

export interface StoryOutline {
  source: string | null;
  format: "json" | "markdown" | "empty" | string;
  title: string;
  items: OutlineItem[];
  nodes?: OutlineNode[];
  content?: string;
  content_source?: string | null;
  source_hash?: string | null;
  importable_items?: OutlineItem[];
  raw?: unknown;
}

export interface StoryCharacter {
  schema_version: number;
  character_id: string;
  slug: string;
  name: string;
  role: string;
  summary: string;
  aliases: string[];
  status: string;
  faction: string;
  tags: string[];
  first_appearance: string;
  profile: string;
  profile_path: string;
  metadata_path: string;
}

export interface StoryCharacterUpdate {
  slug: string;
  name: string;
  role: string;
  summary: string;
  aliases: string[];
  status: string;
  faction: string;
  tags: string[];
  first_appearance: string;
  profile: string;
}

export interface ArchivedStoryCharacter {
  archive_id: string;
  character_id: string;
  slug: string;
  name: string;
  role: string;
  aliases: string[];
  reason: string;
  archived_at: string;
  archive_path: string;
}

export interface StoryCharacters {
  source: string;
  items: StoryCharacter[];
  archives: ArchivedStoryCharacter[];
  warnings: Array<{ path: string; message: string }>;
  migration?: {
    status: "current" | "migrated";
    schema_version: number;
    changed: number;
    created_metadata: number;
    snapshot_path: string | null;
    warnings: Array<{ path: string; message: string }>;
    last_run: {
      changed: number;
      created_metadata: number;
      snapshot_path: string | null;
      completed_at: string;
    } | null;
  };
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
  character_ids: string[];
}

export interface StoryChapterMetadataUpdate {
  status: string;
  summary: string;
  target_characters: number;
  revision: number;
  outline_id: string;
  character_ids: string[];
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
  character_ids: string[];
  outline_ids: string[];
  related_files: string[];
  tags: string[];
  notes: string;
  verification?: ForeshadowVerification;
}

export interface ForeshadowVerification {
  status: "unknown" | "verified" | "review" | "confirmed" | string;
  checked_at?: string;
  confirmed_at?: string;
  action?: string;
  chapter_path?: string;
  evidence_match?: boolean;
  issues?: string[];
  note?: string;
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

export type ToolCategory = "generate" | "edit" | "search" | "review" | "manage" | "patch" | "workspace" | "other";
export type ToolWritePolicy = "none" | "direct" | "proposal" | "workspace_only";

export interface ToolGovernance {
  category: ToolCategory;
  write_policy: ToolWritePolicy;
  requires_confirmation: boolean;
  agent_boundary: string;
}

export interface ToolSummary {
  name: string;
  description: string;
  has_frontend_ui: boolean;
  agent_internal?: boolean;
  input_schema: Record<string, unknown>;
  ui_schema: Record<string, unknown> | null;
  default_preset_id: string | null;
  default_agent: string | null;
  file_access: ToolFileAccess;
  governance?: ToolGovernance | null;
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
  request_timeout: number;
  context_window: "economy" | "standard" | "long" | "maximum";
  effort: string;
  enable_thinking: boolean;
  prompt_cache: boolean;
  native_web_search: boolean;
  web_search_provider: "auto" | "tavily" | "bing" | "native";
  tavily_api_key: string | null;
  tavily_api_key_env: string;
  tavily_search_depth: "basic" | "advanced";
  web_search_max_results: number;
  tavily_include_raw_content: boolean;
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

export interface PromptPackExample {
  id: string;
  name: string;
  category: PromptPackCategory;
  stages: PromptPackStage[];
  description: string;
  content: string;
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

export interface ProjectSystemRules {
  mode: "default" | "project";
  content: string;
  default_content: string;
  updated_at: string | null;
}

/* ── 工作流 ── */

export type WorkflowRunStatus = "draft" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type WorkflowStepStatus = "pending" | "running" | "waiting_user" | "completed" | "failed" | "skipped";
export type WorkflowStepKind = "plan" | "context" | "draft" | "revise" | "check" | "write_file" | "chapter" | "user_confirm" | "custom";

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

export interface ChapterBatchWorkflowCreate {
  start_chapter: number;
  end_chapter: number;
  volume: string;
  requirements: string;
  preset_id: string | null;
  prompt_pack_ids?: string[];
  target_characters: number;
  overwrite_existing: boolean;
  title?: string | null;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  workflow_type: string;
  input_summary: string;
  steps: Array<Partial<WorkflowStepRecord> & { name: string }>;
}

export interface WorkflowStepUpdate {
  name?: string;
  kind?: WorkflowStepKind;
  status?: WorkflowStepStatus;
  preset_id?: string | null;
  prompt_pack_ids?: string[];
  context_pack_ids?: string[];
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  output_path?: string | null;
  error?: string | null;
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
