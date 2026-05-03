/* ── 视图类型 ── */

export type ViewId = "chat" | "tools" | "settings" | "files";

export interface ProjectInfo {
  name: string;
  path: string;
}

/* ── Agent 事件 ── */

export interface AgentEvent {
  type: string;
  content?: string;
  ui_hint?: Record<string, unknown>;
  sender?: "user" | "agent";
  conversation_id?: string;
}

/* ── 对话历史 ── */

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
  messages: ConversationMessage[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

/* ── 工具 ── */

export interface ToolSummary {
  name: string;
  description: string;
  has_frontend_ui: boolean;
  ui_schema: Record<string, unknown> | null;
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

export interface PresetUpdate {
  name?: string;
  llm?: Partial<LLMParams>;
  behavior?: Partial<AgentBehavior>;
}

/* ── 工具执行结果 ── */

export interface ToolResult {
  content: string;
  ui_hint?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

/** 工具完整描述（含 schema，API 返回） */
export type ToolDescriptor = ToolSummary;
