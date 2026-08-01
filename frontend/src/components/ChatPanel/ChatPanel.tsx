import { useCallback, useMemo, useRef, useEffect, useLayoutEffect, useState, type KeyboardEvent } from "react";
import type { AgentEvent, AgentRunRecord, ConversationStatus, ToolDescriptor, WebSource } from "../../types";
import { AiRender, eventToRender } from "../AiRender";
import type { WorkspaceChangeNotice } from "../AiRender/types";
import MarkdownView from "../MarkdownView";
import "./ChatPanel.css";

interface ChatPanelProps {
  events: AgentEvent[];
  historyVersion: number;
  connected: boolean;
  conversationStatus?: ConversationStatus | null;
  conversationLastError?: string | null;
  activeRun?: AgentRunRecord | null;
  tools: ToolDescriptor[];
  onSend: (
    content: string,
    enabledTools?: string[] | null,
    options?: { modelContent?: string; metadata?: Record<string, unknown> },
  ) => void;
  onInterrupt: () => void;
  onRetryRun?: (runId: string) => void;
  onContinueWithError?: (error: string) => void;
  onWorkspaceChanged?: (notice: WorkspaceChangeNotice) => void | Promise<void>;
  input: string;
  onInputChange: (value: string) => void;
  showConversations?: boolean;
  onToggleConversations?: () => void;
}

const INITIAL_HISTORY_WINDOW = 120;
const HISTORY_PAGE_STEP = 80;
const BOTTOM_STICKY_DISTANCE = 96;
const IGNORED_RUN_ISSUES_STORAGE_KEY = "aisync.ignoredRunIssues.v1";
const IGNORED_RUN_ISSUES_LIMIT = 50;
const REFERENCE_CONTEXT_HEADER = "[引用上下文，供本轮回复参考]";
const REFERENCE_CONTEXT_FOOTER = "[/引用上下文]";
const CONSISTENCY_TOOL_NAME = "consistency_check";
const FILE_CHANGE_PROPOSAL_TOOL_NAME = "file_change_proposal";
const EDITING_TOOL_NAMES = new Set([
  "write_chapter",
  "edit_chapter",
  "update_worldview",
  "outline_generate",
  "create_character",
  "character_manage",
  "foreshadow_manage",
]);

/** 合并流式事件，并把同一轮的 stream + agent_final 折叠成一条消息。 */
function mergeStreamEvents(events: AgentEvent[]): AgentEvent[] {
  const merged: AgentEvent[] = [];
  for (const event of events) {
    if (event.type === "stream_end") continue;
    if (event.type === "agent_final") {
      const lastUserIndex = findLastIndex(merged, (item) => item.sender === "user" && item.type === "user_message");
      const duplicateFinalIndex = findLastIndex(
        merged,
        (item, index) =>
          index > lastUserIndex &&
          item.type === "agent_final" &&
          normalizeContent(item.content) === normalizeContent(event.content),
      );
      if (duplicateFinalIndex >= 0) continue;

      const streamIndex = findLastIndex(
        merged,
        (item, index) => index > lastUserIndex && item.type === "stream" && item.sender !== "user",
      );
      if (streamIndex >= 0) {
        merged[streamIndex] = {
          ...merged[streamIndex],
          ...event,
          type: "agent_final",
          sender: "agent",
          content: event.content ?? merged[streamIndex].content,
        };
        continue;
      }
    }
    if (event.type === "stream") {
      const last = merged[merged.length - 1];
      if (last && last.type === "stream") {
        last.content = (last.content ?? "") + (event.content ?? "");
        continue;
      }
      merged.push({ ...event, sender: "agent" });
    } else {
      merged.push(event);
    }
  }
  return merged;
}

function findLastIndex<T>(items: T[], predicate: (item: T, index: number) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index], index)) return index;
  }
  return -1;
}

function normalizeContent(content?: string) {
  return (content ?? "").replace(/\s+/g, " ").trim();
}

function webSourcesFromEvent(event: AgentEvent): WebSource[] {
  const raw = event.metadata?.web_sources;
  if (!Array.isArray(raw)) return [];
  const sources = new Map<string, WebSource>();
  for (const item of raw) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const source = item as Record<string, unknown>;
    const url = typeof source.url === "string" ? source.url.trim() : "";
    if (!/^https?:\/\//i.test(url) || sources.has(url)) continue;
    sources.set(url, {
      url,
      title: typeof source.title === "string" ? source.title.trim() : "",
      snippet: typeof source.snippet === "string" ? source.snippet.trim() : "",
      provider: typeof source.provider === "string" ? source.provider.trim() : "",
    });
    if (sources.size >= 12) break;
  }
  return [...sources.values()];
}

function webSourceHost(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}

function WebSourceList({ event }: { event: AgentEvent }) {
  if (event.type !== "agent_final") return null;
  const sources = webSourcesFromEvent(event);
  if (!sources.length) return null;
  return (
    <details className="chat-web-sources">
      <summary>
        <strong>参考来源</strong>
        <span>{sources.length} 项</span>
      </summary>
      <div className="chat-web-sources-list">
        {sources.map((source, index) => (
          <article key={source.url}>
            <span>{index + 1}</span>
            <div>
              <a href={source.url} target="_blank" rel="noreferrer noopener">
                {source.title || webSourceHost(source.url)}
              </a>
              <small>{webSourceHost(source.url)}</small>
              {source.snippet && <p>{source.snippet}</p>}
            </div>
          </article>
        ))}
      </div>
    </details>
  );
}

function readIgnoredRunIssueIds() {
  if (typeof window === "undefined") return new Set<string>();
  try {
    const raw = window.localStorage.getItem(IGNORED_RUN_ISSUES_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set<string>();
    return new Set(parsed.filter((item): item is string => typeof item === "string" && item.length > 0));
  } catch {
    return new Set<string>();
  }
}

function writeIgnoredRunIssueIds(ids: Set<string>) {
  if (typeof window === "undefined") return;
  const limited = [...ids].slice(-IGNORED_RUN_ISSUES_LIMIT);
  try {
    window.localStorage.setItem(IGNORED_RUN_ISSUES_STORAGE_KEY, JSON.stringify(limited));
  } catch {
    // Storage can be unavailable in some embedded modes; the in-memory state still works.
  }
}

function memoryStatusText(event: AgentEvent) {
  const memory = event.memory ?? {};
  const parts = [`近期 ${memory.recent_messages ?? 0}/${memory.recent_window ?? "?"} 条`];
  if (typeof memory.total_message_count === "number") parts.push(`总计 ${memory.total_message_count} 条`);
  if (typeof memory.old_message_count === "number" && memory.old_message_count > 0) parts.push(`旧消息 ${memory.old_message_count} 条`);
  parts.push(memory.summary ? `已注入摘要 ${memory.summary_chars ?? 0} 字符` : "无摘要");
  if (memory.summary_updated_at) parts.push(`摘要更新 ${new Date(memory.summary_updated_at).toLocaleString()}`);
  if (memory.summary_pending) parts.push("摘要后台更新中");
  const quality = memory.summary_quality;
  if (quality?.status === "weak" || quality?.status === "poor") {
    parts.push(`摘要${quality.score ?? 0}分`);
  } else if (quality?.status === "ok") {
    parts.push(`摘要${quality.score ?? 0}分`);
  }
  return parts.join(" · ");
}

function isSystemStatusEvent(event: AgentEvent) {
  return event.type === "memory_status"
    || event.type === "agent_limit_reached"
    || event.type === "agent_intervention_required"
    || event.type === "output_truncated"
    || event.type === "agent_status"
    || event.type === "prompt_audit";
}

function isTaskListEvent(event: AgentEvent) {
  return event.type === "agent_task_list";
}

function isAgentRunEvent(event: AgentEvent) {
  return event.type === "agent_run";
}

function isPromptAuditEvent(event: AgentEvent) {
  return event.type === "prompt_audit";
}

function isToolResultEvent(event: AgentEvent) {
  return event.type === "tool_result";
}

function uiHintType(event: AgentEvent) {
  const type = event.ui_hint?.type;
  return typeof type === "string" ? type : "";
}

function systemStatusText(event: AgentEvent) {
  if (event.type === "agent_limit_reached") return event.content ?? "Agent 已达到本轮迭代上限。";
  if (event.type === "agent_intervention_required") return event.content ?? "Agent 等待人工选择";
  if (event.type === "agent_status") return event.content ?? "Agent 正在工作";
  if (event.type === "prompt_audit") return event.content ?? "提示词来源已记录";
  return memoryStatusText(event);
}

function isErrorEvent(event: AgentEvent) {
  return event.type === "error";
}

function toolStatusText(event: AgentEvent) {
  const name = event.tool?.name ?? "unknown";
  if (name === "web_search") {
    if (event.type === "tool_call_start") return "正在联网搜索";
    if (event.type === "tool_call_error") return "联网搜索失败";
    return "联网搜索完成";
  }
  if (event.type === "tool_call_start") return `调用工具 ${name}`;
  if (event.type === "tool_call_error") return `工具 ${name} 失败`;
  return `工具 ${name} 完成`;
}

function toolParamsText(params?: Record<string, unknown>) {
  const entries = Object.entries(params ?? {});
  if (!entries.length) return "";
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
}

function shortContent(content?: string, limit = 160) {
  const text = (content ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trim()}...`;
}

function uiHintItemCount(event: AgentEvent) {
  const data = event.ui_hint?.data;
  if (Array.isArray(data)) return data.length;
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const items = (data as { items?: unknown }).items;
    return Array.isArray(items) ? items.length : null;
  }
  return null;
}

function changeSetItemCount(event: AgentEvent) {
  const data = event.ui_hint?.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return 0;
  const changes = (data as { changes?: unknown }).changes;
  return Array.isArray(changes) ? changes.length : 0;
}

function appliedWorkspaceChange(event: AgentEvent): WorkspaceChangeNotice | null {
  const data = event.ui_hint?.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const record = data as Record<string, unknown>;
  if (record.status !== "applied" || typeof record.id !== "string") return null;
  const rawChanges = Array.isArray(record.changes) ? record.changes : [];
  const changes = rawChanges.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const change = item as Record<string, unknown>;
    if (typeof change.path !== "string" || !["write", "delete"].includes(String(change.operation))) return [];
    return [{ path: change.path, operation: change.operation as "write" | "delete" }];
  });
  return { changeSetId: record.id, changes };
}

function toolResultTitle(event: AgentEvent) {
  const type = uiHintType(event);
  if (type === "changeset:proposal") return "待确认文件改动";
  if (type === "list:search_results") return "检索结果";
  if (type === "list:web_sources") return "联网搜索结果";
  if (type === "list:issues") return "一致性检查结果";
  if (type === "list:foreshadows") return "伏笔梳理结果";
  if (type === "document:worldview") return "世界观文档结果";
  if (type === "stream:editor") return "写作结果";
  if (type === "card:character") return "角色结果";
  if (type === "list:outline_chapters") return "大纲结果";
  return type || "工具结果";
}

function toolResultSummary(event: AgentEvent) {
  const type = uiHintType(event);
  const count = uiHintItemCount(event);
  if (type === "changeset:proposal") return `${changeSetItemCount(event)} 个文件 · 等待确认`;
  if (type === "list:search_results") return `${count ?? 0} 条检索结果`;
  if (type === "list:web_sources") return count ? `${count} 个可验证来源` : "未返回可验证来源";
  if (type === "list:issues") return `${count ?? 0} 条一致性提示`;
  if (type === "list:foreshadows") return `${count ?? 0} 条伏笔记录`;
  if (type === "list:outline_chapters") return `${count ?? 0} 个大纲节点`;
  if (type === "card:character") return "角色卡片";
  if (type === "document:worldview") return "世界观文档";
  if (type === "stream:editor") return "写作输出";
  return shortContent(event.content, 96) || "点击展开查看详情";
}

function isToolStatusEvent(event: AgentEvent) {
  return event.type === "tool_call_start" || event.type === "tool_call_end" || event.type === "tool_call_error";
}

function agentActivityText(event: AgentEvent) {
  if (event.type === "agent_status") return event.content ?? "Agent 正在工作";
  if (event.tool?.name === "web_search") {
    if (event.type === "tool_call_start") return "正在联网搜索";
    if (event.type === "tool_call_error") return "联网搜索失败";
    if (event.type === "tool_call_end") return "联网搜索完成";
  }
  if (event.type === "tool_call_start") return `调用工具 ${event.tool?.name ?? "unknown"}`;
  if (event.type === "tool_call_error") return event.content ?? `工具 ${event.tool?.name ?? "unknown"} 失败`;
  if (event.type === "tool_call_end") return `工具 ${event.tool?.name ?? "unknown"} 已完成`;
  if (event.type === "stream") return "正在生成回复";
  if (event.type === "agent_final") return "回复已完成";
  if (event.type === "agent_limit_reached") return event.content ?? "Agent 已暂停";
  if (event.type === "error") return event.content ?? "前台错误";
  return "";
}

function getWorkState(events: AgentEvent[], connected: boolean) {
  let pending = false;
  let label = connected ? "已连接" : "未连接";
  let kind: "idle" | "working" | "done" | "error" = "idle";

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const phase = typeof event.metadata?.phase === "string" ? event.metadata.phase : "";
    if (event.type === "agent_final") {
      const termination = event.metadata?.termination_reason;
      if (termination === "human_intervention" || termination === "awaiting_choice") {
        return { label: termination === "awaiting_choice" ? "等待你提交选择" : "等待你处理工具问题", kind: "working" as const };
      }
      return { label: "回复已完成", kind: "done" as const };
    }
    if (event.type === "agent_run" && event.run) {
      if (event.run.status === "running") return { label: event.run.phase_label || "Agent 正在工作", kind: "working" as const };
      if (event.run.status === "failed") return { label: event.run.error ? `本轮失败：${event.run.error}` : "本轮回复失败", kind: "error" as const };
      if (event.run.status === "interrupted") return { label: "本轮回复已中断", kind: "done" as const };
      if (event.run.status === "completed") return { label: "本轮回复已完成", kind: "done" as const };
    }
    if (event.type === "error" || event.type === "agent_limit_reached") {
      return { label: event.content ?? "前台错误", kind: "error" as const };
    }
    if (event.type === "agent_status" && (phase === "done" || phase === "interrupted" || phase === "interrupt_requested")) {
      return { label: event.content ?? "Agent 已停止", kind: "done" as const };
    }
    if (event.type === "agent_status" && phase === "error") {
      return { label: event.content ?? "Agent 出错", kind: "error" as const };
    }
    if (event.type === "stream" || event.type === "agent_status" || isToolStatusEvent(event)) {
      pending = true;
      label = agentActivityText(event) || "AI 正在工作";
      kind = "working";
    }
    if (event.sender === "user" && event.type === "user_message") {
      if (pending) return { label: label || "AI 正在工作", kind: "working" as const };
      return { label: "正在等待响应", kind: "working" as const };
    }
  }

  return { label, kind };
}

function conversationStatusToWorkState(
  status: ConversationStatus | null | undefined,
  lastError: string | null | undefined,
  connected: boolean,
  activeRun?: AgentRunRecord | null,
) {
  if (activeRun?.status === "running") return { label: activeRun.phase_label || "Agent 正在工作", kind: "working" as const };
  if (activeRun?.status === "failed") return { label: activeRun.error ? `本轮失败：${activeRun.error}` : "本轮回复失败", kind: "error" as const };
  if (activeRun?.status === "interrupted") return { label: "本轮回复已中断", kind: "done" as const };
  if (activeRun?.status === "completed") return { label: "本轮回复已完成", kind: "done" as const };
  if (status === "running") return { label: "上次响应未正常结束", kind: "error" as const };
  if (status === "failed") return { label: lastError ? `上次失败：${lastError}` : "上次响应失败", kind: "error" as const };
  if (status === "interrupted") return { label: "上次响应已中断", kind: "done" as const };
  if (status === "waiting_user") return { label: "等待你的选择", kind: "working" as const };
  if (status === "completed") return { label: "上次回复已完成", kind: "done" as const };
  return { label: connected ? "已连接" : "未连接", kind: "idle" as const };
}

function isSelectableMessage(event: AgentEvent) {
  if (!event.content?.trim()) return false;
  if (event.sender === "user" && event.type === "user_message") return true;
  return event.type === "agent_final" || event.type === "stream";
}

function promptAuditItems(run: AgentRunRecord) {
  const audit = run.prompt_audit;
  if (!audit || Object.keys(audit).length === 0) return [];
  const items: string[] = [];
  const systemSource = audit.system_prompt?.source;
  if (systemSource) {
    const base = audit.system_prompt?.base_source === "preset" ? "预设" : "默认";
    const projectRules = audit.system_prompt?.project_rules;
    if (projectRules?.included) {
      items.push(`System: ${base}+AGENT.md`);
    } else {
      items.push(systemSource === "preset" ? "System: 预设" : "System: 默认");
    }
  }
  if (audit.context_window?.label) items.push(`上下文: ${audit.context_window.label}`);
  if (typeof audit.memory?.recent_messages === "number") {
    const injected = audit.memory.injected_recent_messages;
    items.push(`记忆: ${typeof injected === "number" ? `${injected}/` : ""}${audit.memory.recent_messages} 条${audit.memory.summary ? " + 摘要" : ""}`);
  }
  if (typeof audit.vector_context?.count === "number") items.push(`向量: ${audit.vector_context.count} 条`);
  if (audit.foreshadow_context?.included) items.push("伏笔: 已注入");
  if (typeof audit.prompt_packs?.count === "number" && audit.prompt_packs.count > 0) {
    items.push(`提示词: ${audit.prompt_packs.count} 个`);
  }
  if (typeof audit.tools?.count === "number") items.push(`工具: ${audit.tools.count} 个`);
  if (audit.prompt_cache) {
    const prefixCount = audit.prompt_cache.stable_prefix_messages ?? 0;
    items.push(`缓存前缀: ${audit.prompt_cache.enabled ? "开" : "关"}${prefixCount ? `/${prefixCount}段` : ""}`);
  }
  if (audit.tool_continuation?.strategy) items.push(`工具续轮: ${audit.tool_continuation.strategy}`);
  return items;
}

function messageRoleLabel(event: AgentEvent) {
  return event.sender === "user" ? "用户" : "AI";
}

function formatSelectedMessages(events: AgentEvent[]) {
  return events
    .filter(isSelectableMessage)
    .map((event) => `${messageRoleLabel(event)}：\n${event.content?.trim() ?? ""}`)
    .join("\n\n---\n\n");
}

interface QuoteReference {
  role: string;
  content: string;
  lineCount: number;
}

interface ReferencedUserContent {
  content: string;
  referenceLines: number;
  referenceCount: number;
}

function quoteReferencesFromEvents(events: AgentEvent[]) {
  return events
    .filter(isSelectableMessage)
    .map((event) => {
      const content = (event.content ?? "").trim();
      return {
        role: messageRoleLabel(event),
        content,
        lineCount: countContentLines(content),
      };
    })
    .filter((reference) => reference.content);
}

function countContentLines(content: string) {
  return Math.max(1, content.split(/\r?\n/).filter((line) => line.trim()).length);
}

function summarizeQuoteReferences(references: QuoteReference[]) {
  const lineCount = references.reduce((total, reference) => total + reference.lineCount, 0);
  const messageCount = references.length;
  return {
    lineCount,
    messageCount,
    label: messageCount > 1 ? `引用 ${messageCount} 条消息 · ${lineCount} 行文字` : `引用 ${lineCount} 行文字`,
  };
}

function buildModelMessageWithReferences(content: string, references: QuoteReference[]) {
  const message = content.trim();
  if (!references.length) return message;
  const referenceBlock = references
    .map((reference, index) => `[${index + 1}] ${reference.role}（${reference.lineCount}行）\n${reference.content}`)
    .join("\n\n");
  return `${message}\n\n${REFERENCE_CONTEXT_HEADER}\n${referenceBlock}\n${REFERENCE_CONTEXT_FOOTER}`;
}

function metadataReferencedUserContent(content: string, metadata?: Record<string, unknown>): ReferencedUserContent | null {
  const referenceLines = Number(metadata?.quote_reference_lines ?? 0);
  const referenceCount = Number(metadata?.quote_reference_count ?? 0);
  if (referenceLines <= 0) return null;
  return { content, referenceLines, referenceCount };
}

function markerReferencedUserContent(content?: string): ReferencedUserContent {
  const raw = content ?? "";
  const headerIndex = raw.lastIndexOf(REFERENCE_CONTEXT_HEADER);
  if (headerIndex < 0) {
    return { content: raw, referenceLines: 0, referenceCount: 0 };
  }
  const footerIndex = raw.indexOf(REFERENCE_CONTEXT_FOOTER, headerIndex + REFERENCE_CONTEXT_HEADER.length);
  const referenceBlock = raw
    .slice(headerIndex + REFERENCE_CONTEXT_HEADER.length, footerIndex >= 0 ? footerIndex : raw.length)
    .trim();
  const referenceLines = [...referenceBlock.matchAll(/（(\d+)行）/g)]
    .reduce((total, match) => total + Number(match[1] || 0), 0);
  const referenceCount = (referenceBlock.match(/^\[\d+\]/gm) ?? []).length;
  return {
    content: raw.slice(0, headerIndex).trimEnd(),
    referenceLines: referenceLines || countContentLines(referenceBlock),
    referenceCount,
  };
}

function displayReferencedUserContent(content?: string, metadata?: Record<string, unknown>): ReferencedUserContent {
  return metadataReferencedUserContent(content ?? "", metadata) ?? markerReferencedUserContent(content);
}

interface ChoiceOption {
  id: string;
  label: string;
  value: string;
  description?: string;
}

interface ChoiceGroup {
  id: string;
  title: string;
  description?: string;
  mode: "single" | "multiple";
  required: boolean;
  minSelections: number;
  maxSelections: number;
  options: ChoiceOption[];
}

interface ChoiceRequest {
  requestId: string;
  groups: ChoiceGroup[];
}

interface ChoiceResponseSelection {
  group_id: string;
  option_ids: string[];
  labels: string[];
  values: string[];
}

interface ChoiceResponse {
  request_id: string;
  selections: ChoiceResponseSelection[];
}

interface AgentTaskItem {
  label: string;
  status: "pending" | "active" | "done" | "error";
}

interface AgentTaskList {
  tasks: AgentTaskItem[];
  activeLabel: string;
  done: boolean;
}

function parseAgentTaskList(event?: AgentEvent): AgentTaskList | null {
  const rawTasks = event?.metadata?.tasks;
  if (!Array.isArray(rawTasks)) return null;
  const tasks = rawTasks
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const label = typeof record.label === "string" ? record.label : "";
      const rawStatus = typeof record.status === "string" ? record.status : "pending";
      const status = ["pending", "active", "done", "error"].includes(rawStatus)
        ? rawStatus as AgentTaskItem["status"]
        : "pending";
      return label ? { label, status } : null;
    })
    .filter((item): item is AgentTaskItem => Boolean(item));
  if (!tasks.length) return null;
  const active = tasks.find((task) => task.status === "active");
  return {
    tasks,
    activeLabel: active?.label ?? (tasks.every((task) => task.status === "done") ? "任务已完成" : tasks[0].label),
    done: tasks.every((task) => task.status === "done"),
  };
}

function fallbackTaskListFromEvents(events: AgentEvent[], activeRun?: AgentRunRecord | null): AgentTaskList | null {
  const latest = [...events].reverse().find((event) => (
    event.type === "agent_status" ||
    event.type === "stream" ||
    event.type === "tool_call_start" ||
    event.type === "tool_call_end" ||
    event.type === "tool_call_error" ||
    event.type === "agent_final" ||
    event.type === "error" ||
    event.type === "prompt_audit"
  ));
  if (!latest && !activeRun) return null;

  const labels = ["检索上下文", "请求模型", "生成回复", "整理完成"];
  const phase = activeRun?.phase || (typeof latest?.metadata?.phase === "string" ? latest.metadata.phase : "");
  const status = activeRun?.status;
  const waitingForUser = status === "waiting_user" || (
    latest?.type === "agent_final"
    && ["human_intervention", "awaiting_choice"].includes(String(latest.metadata?.termination_reason ?? ""))
  );
  let activeIndex = 0;
  let done = status === "completed" || (latest?.type === "agent_final" && !waitingForUser);
  const hasError = status === "failed" || latest?.type === "error" || latest?.type === "tool_call_error";

  if (phase === "thinking" || phase === "context_ready") activeIndex = 1;
  if (
    phase === "tool_calling" ||
    phase === "chapter_drafting" ||
    latest?.type === "stream" ||
    latest?.type === "tool_call_start" ||
    latest?.type === "tool_call_end"
  ) activeIndex = 2;
  if (phase === "finalizing" || phase === "done" || status === "completed" || latest?.type === "agent_final") activeIndex = 3;
  if (status === "interrupted" || phase === "interrupted" || phase === "interrupt_requested") {
    activeIndex = 3;
    done = true;
  }
  if (waitingForUser) activeIndex = 3;

  const tasks = labels.map((label, index) => {
    let itemStatus: AgentTaskItem["status"] = index < activeIndex ? "done" : index === activeIndex ? "active" : "pending";
    if (done) itemStatus = "done";
    if (hasError && index === activeIndex) itemStatus = "error";
    return { label, status: itemStatus };
  });

  return {
    tasks,
    activeLabel: waitingForUser ? "等待你的选择" : done ? "任务已完成" : hasError ? "任务失败" : labels[activeIndex],
    done,
  };
}

function runStatusLabel(run: AgentRunRecord) {
  if (run.status === "running") return run.phase_label || "运行中";
  if (run.status === "completed") return "已完成";
  if (run.status === "failed") return run.error ? `失败：${run.error}` : "失败";
  if (run.status === "interrupted") return "已中断";
  if (run.status === "waiting_user") return "等待选择";
  return run.status;
}

function runStatusClass(run: AgentRunRecord) {
  if (run.status === "running") return "is-active";
  if (run.status === "waiting_user") return "is-active";
  if (run.status === "failed") return "is-error";
  return "is-done";
}

function formatRunTime(value?: string | null) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString();
}

function formatCount(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  return value >= 10000 ? `${(value / 10000).toFixed(1)}万` : String(value);
}

function runUsageItems(run: AgentRunRecord) {
  const usage = run.prompt_audit?.usage;
  if (!usage) return [];
  const items: string[] = [];
  if (typeof usage.model_request_attempts === "number") items.push(`请求尝试: ${usage.model_request_attempts}`);
  if (typeof usage.model_requests === "number") items.push(`成功返回: ${usage.model_requests}`);
  if (typeof usage.request_timeout_seconds === "number") {
    const mode = usage.request_timeout_mode === "idle" ? "空闲超时" : "总超时";
    items.push(`${mode}: ${usage.request_timeout_seconds}s`);
  }
  if (usage.request_stream_requested) items.push("流式: 是");
  if (usage.last_request_phase) items.push(`阶段: ${requestPhaseLabel(usage.last_request_phase)}`);
  if (Array.isArray(usage.tool_batches) && usage.tool_batches.length > 0) {
    items.push(`工具轮次: ${usage.tool_batches.length}`);
  }
  if (typeof usage.duplicate_tool_calls === "number" && usage.duplicate_tool_calls > 0) {
    items.push(`重复跳过: ${usage.duplicate_tool_calls}`);
  }
  if (typeof usage.failed_tool_calls === "number" && usage.failed_tool_calls > 0) {
    items.push(`工具失败: ${usage.failed_tool_calls}`);
  }
  if (typeof usage.coalesced_change_proposals === "number" && usage.coalesced_change_proposals > 0) {
    items.push(`改动包合并: ${usage.coalesced_change_proposals}`);
  }
  if (Array.isArray(usage.applied_change_sets) && usage.applied_change_sets.length > 0) {
    const verified = usage.applied_change_sets.filter((item) => item.status === "verified").length;
    items.push(`改动核验: ${verified}/${usage.applied_change_sets.length}`);
  }
  if (typeof usage.safe_finalize_attempts === "number" && usage.safe_finalize_attempts > 0) {
    items.push(`兼容收尾: ${usage.safe_finalize_attempts}`);
  }
  if (typeof usage.consecutive_no_progress_batches === "number" && usage.consecutive_no_progress_batches > 0) {
    items.push(`连续无进展: ${usage.consecutive_no_progress_batches}`);
  }
  if (usage.termination_reason && usage.termination_reason !== "running") {
    const terminationLabels: Record<string, string> = {
      completed: "正常完成",
      interrupted: "用户中断",
      iteration_limit: "达到轮次上限",
      tool_stalled: "工具无进展",
      human_intervention: "等待人工选择",
      awaiting_choice: "等待用户选择",
      output_truncated: "达到输出上限",
    };
    items.push(`结束原因: ${terminationLabels[usage.termination_reason] ?? usage.termination_reason}`);
  }
  if (Array.isArray(usage.change_approvals) && usage.change_approvals.length > 0) {
    const applied = usage.change_approvals.filter((item) => item.decision === "applied").length;
    const discarded = usage.change_approvals.filter((item) => item.decision === "discarded").length;
    items.push(`改动确认: 应用 ${applied} · 丢弃 ${discarded}`);
  }
  const exactTotal = typeof usage.total_tokens === "number" && usage.total_tokens > 0 ? usage.total_tokens : null;
  const estimatedTotal = typeof usage.estimated_total_tokens === "number" && usage.estimated_total_tokens > 0
    ? usage.estimated_total_tokens
    : null;
  if (exactTotal) items.push(`Token: ${formatCount(exactTotal)}`);
  else if (estimatedTotal) items.push(`估算Token: ${formatCount(estimatedTotal)}`);
  if (typeof usage.search_credits === "number" && usage.search_credits > 0) {
    items.push(`联网额度: ${usage.search_credits.toLocaleString()} credits`);
  }
  if (typeof usage.last_request_estimated_input_tokens === "number") {
    items.push(`本轮输入估算: ${formatCount(usage.last_request_estimated_input_tokens)}`);
  }
  if (typeof usage.tool_calls === "number") items.push(`工具调用: ${usage.tool_calls}`);
  const lastCall = Array.isArray(usage.llm_calls) ? usage.llm_calls[usage.llm_calls.length - 1] : null;
  if (lastCall) {
    const parts = [
      `#${lastCall.index ?? usage.llm_calls?.length ?? 1}`,
      requestPhaseLabel(lastCall.phase),
      lastCall.status,
      typeof lastCall.estimated_input_tokens === "number" ? `${formatCount(lastCall.estimated_input_tokens)} token` : "",
      typeof lastCall.tool_count === "number" ? `工具schema ${lastCall.tool_count}` : "",
    ].filter(Boolean);
    items.push(`最后请求: ${parts.join(" · ")}`);
  }
  if (usage.last_error_category) items.push(`错误: ${errorCategoryLabel(usage.last_error_category)}`);
  return items;
}

function requestPhaseLabel(phase?: string | null) {
  if (phase === "tool_finalize") return "工具收尾";
  if (phase === "tool_continue") return "工具续轮";
  if (phase === "initial") return "首轮";
  return phase || "模型";
}

function errorCategoryLabel(category: string) {
  const labels: Record<string, string> = {
    timeout: "超时",
    rate_limit: "限流/额度",
    auth: "鉴权",
    bad_request: "参数",
    network: "网络",
    llm_error: "模型",
  };
  return labels[category] ?? category;
}

function runSummaryItems(run?: AgentRunRecord | null) {
  if (!run) return [];
  const items = runUsageItems(run);
  const toolCount = run.tool_calls.length;
  if (toolCount > 0 && !items.some((item) => item.startsWith("工具调用:"))) {
    items.push(`工具调用: ${toolCount}`);
  }
  return items.slice(0, 3);
}

function runErrorDetail(run: AgentRunRecord) {
  const usage = run.prompt_audit?.usage;
  const category = usage?.last_error_category;
  const message = usage?.last_error_message;
  if (!category && !message) return "";
  return [category ? `类型：${errorCategoryLabel(category)}` : "", message ? `详情：${message}` : ""]
    .filter(Boolean)
    .join("；");
}

function runErrorDetailText(run: AgentRunRecord) {
  const usage = run.prompt_audit?.usage;
  const category = usage?.last_error_category;
  const message = usage?.last_error_message;
  if (!category && !message) return "";
  return [category ? `类型：${errorCategoryLabel(category)}` : "", message ? `详情：${message}` : ""]
    .filter(Boolean)
    .join("；");
}

function runRecoverySuggestion(run?: AgentRunRecord | null) {
  const category = run?.prompt_audit?.usage?.last_error_category;
  if (!category) {
    if (run?.status === "interrupted") return "本轮已中断。可以直接发送新消息，或重试上次输入。";
    return "";
  }
  const suggestions: Record<string, string> = {
    timeout: "模型长时间没有新内容返回。可以调大本预设的请求超时，换更快的模型，或减少本轮上下文后重试。",
    rate_limit: "模型限流或额度不足。可以稍后再试，或切换到备用/便宜模型。",
    auth: "模型鉴权失败。检查 API Key、环境变量名和 API Base 是否匹配。",
    bad_request: "模型请求参数不兼容。优先检查模型名、thinking 开关、工具调用兼容性和 API Base。",
    network: "模型网络连接失败。检查代理、网络、API Base，或稍后重试。",
    llm_error: "模型请求失败。复制错误详情后检查模型服务返回，必要时换预设重试。",
  };
  return suggestions[category] ?? "模型请求失败。复制错误详情后检查配置，必要时换预设重试。";
}

const MUTATING_AGENT_TOOLS = new Set([
  "chapter_draft",
  "character_manage",
  "create_character",
  "edit_chapter",
  "file_change_proposal",
  "foreshadow_manage",
  "outline_generate",
  "update_worldview",
  "write_chapter",
]);

function runNeedsSafeFinalize(run?: AgentRunRecord | null) {
  if (!run) return false;
  if (run.retry_mode === "finalize") return true;
  const usage = run.prompt_audit?.usage;
  if (Array.isArray(usage?.applied_change_sets) && usage.applied_change_sets.length > 0) return true;
  if (
    Array.isArray(usage?.change_approvals)
    && usage.change_approvals.some((item) => item?.decision === "applied")
  ) return true;
  return run.tool_calls.some(
    (tool) => tool.status === "completed" && MUTATING_AGENT_TOOLS.has(tool.name ?? ""),
  );
}

function retryActionLabel(run?: AgentRunRecord | null) {
  return runNeedsSafeFinalize(run) ? "继续收尾" : "重新发送";
}

function toolRunLabel(tool: AgentRunRecord["tool_calls"][number]) {
  const parts = [tool.name ?? "unknown", tool.status ?? "completed"];
  if (tool.mode) parts.push(tool.mode === "invoke" ? "AI" : tool.mode);
  if (tool.preset_id) parts.push(tool.preset_id);
  if (typeof tool.duration_ms === "number") parts.push(`${tool.duration_ms}ms`);
  return parts.join(" · ");
}

function runToolEvent(tool: AgentRunRecord["tool_calls"][number], conversationId: string): AgentEvent {
  const type = tool.status === "running"
    ? "tool_call_start"
    : tool.status === "failed"
      ? "tool_call_error"
      : "tool_call_end";
  return {
    type,
    content: tool.error ?? undefined,
    conversation_id: conversationId,
    sender: "agent",
    metadata: { restored_from_run: true },
    tool: {
      call_id: tool.call_id,
      name: tool.name,
      params: tool.params,
      duration_ms: tool.duration_ms ?? undefined,
      error: tool.error ?? undefined,
    },
  };
}

function parseChoiceRequest(event: AgentEvent): ChoiceRequest | null {
  if (event.type !== "agent_final") return null;
  const raw = event.metadata?.choice_request;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const requestId = typeof record.request_id === "string" ? record.request_id.trim() : "";
  if (!requestId || !Array.isArray(record.groups)) return null;

  const groups = record.groups.map((item): ChoiceGroup | null => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const group = item as Record<string, unknown>;
    const id = typeof group.id === "string" ? group.id.trim() : "";
    const title = typeof group.title === "string" ? group.title.trim() : "";
    const mode = group.mode === "multiple" ? "multiple" : group.mode === "single" ? "single" : null;
    if (!id || !title || !mode || !Array.isArray(group.options)) return null;
    const options = group.options.map((option): ChoiceOption | null => {
      if (!option || typeof option !== "object" || Array.isArray(option)) return null;
      const value = option as Record<string, unknown>;
      const optionId = typeof value.id === "string" ? value.id.trim() : "";
      const label = typeof value.label === "string" ? value.label.trim() : "";
      const optionValue = typeof value.value === "string" ? value.value : label;
      if (!optionId || !label) return null;
      return {
        id: optionId,
        label,
        value: optionValue,
        description: typeof value.description === "string" ? value.description.trim() : undefined,
      };
    }).filter((option): option is ChoiceOption => Boolean(option));
    if (options.length < 2) return null;
    const required = group.required !== false;
    const defaultMin = required ? 1 : 0;
    const minSelections = mode === "single"
      ? defaultMin
      : Math.max(0, Number.isInteger(group.min_selections) ? Number(group.min_selections) : defaultMin);
    const maxSelections = mode === "single"
      ? 1
      : Math.min(options.length, Math.max(1, Number.isInteger(group.max_selections) ? Number(group.max_selections) : options.length));
    return {
      id,
      title,
      description: typeof group.description === "string" ? group.description.trim() : undefined,
      mode,
      required,
      minSelections,
      maxSelections,
      options,
    };
  }).filter((group): group is ChoiceGroup => Boolean(group));
  return groups.length ? { requestId, groups } : null;
}

function parseChoiceResponse(event: AgentEvent): ChoiceResponse | null {
  if (event.sender !== "user") return null;
  const raw = event.metadata?.choice_response;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const response = raw as Record<string, unknown>;
  if (typeof response.request_id !== "string" || !Array.isArray(response.selections)) return null;
  const selections = response.selections.map((item): ChoiceResponseSelection | null => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const selection = item as Record<string, unknown>;
    if (typeof selection.group_id !== "string") return null;
    const stringArray = (value: unknown) => Array.isArray(value)
      ? value.filter((entry): entry is string => typeof entry === "string")
      : [];
    return {
      group_id: selection.group_id,
      option_ids: stringArray(selection.option_ids),
      labels: stringArray(selection.labels),
      values: stringArray(selection.values),
    };
  }).filter((item): item is ChoiceResponseSelection => Boolean(item));
  return { request_id: response.request_id, selections };
}

export default function ChatPanel({
  events,
  historyVersion,
  connected,
  conversationStatus,
  conversationLastError,
  activeRun,
  tools,
  onSend,
  onInterrupt,
  onRetryRun,
  onContinueWithError,
  onWorkspaceChanged,
  input,
  onInputChange,
  showConversations,
  onToggleConversations,
}: ChatPanelProps) {
  const messagesRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const pendingScrollTargetRef = useRef<"top" | "bottom" | null>(null);
  const notifiedChangeSetsRef = useRef<Set<string>>(new Set());
  const [toolsOpen, setToolsOpen] = useState(false);
  const [selectedTools, setSelectedTools] = useState<string[] | null>(null);
  const [consistencyCheckEnabled, setConsistencyCheckEnabled] = useState(false);
  const [autoApplyFileChanges, setAutoApplyFileChanges] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedMessageIndexes, setSelectedMessageIndexes] = useState<Set<number>>(() => new Set());
  const [quoteReferences, setQuoteReferences] = useState<QuoteReference[]>([]);
  const [expandedToolResults, setExpandedToolResults] = useState<Set<number>>(() => new Set());
  const [lastTaskList, setLastTaskList] = useState<ReturnType<typeof parseAgentTaskList>>(null);
  const [taskDetailsOpen, setTaskDetailsOpen] = useState(false);
  const [expandedSystemDetails, setExpandedSystemDetails] = useState(false);
  const [choiceSelections, setChoiceSelections] = useState<Record<string, Record<string, string[]>>>({});
  const [ignoredRunIssueIds, setIgnoredRunIssueIds] = useState<Set<string>>(() => readIgnoredRunIssueIds());
  const [visibleStart, setVisibleStart] = useState(0);
  const [liveStart, setLiveStart] = useState(0);
  const displayEvents = useMemo(() => mergeStreamEvents(events), [events]);
  const liveEvents = useMemo(() => displayEvents.slice(liveStart), [displayEvents, liveStart]);
  const liveTaskList = useMemo(() => {
    const latest = [...liveEvents].reverse().find(isTaskListEvent);
    return parseAgentTaskList(latest);
  }, [liveEvents]);
  const fallbackTaskList = useMemo(
    () => fallbackTaskListFromEvents(liveEvents, activeRun),
    [activeRun, liveEvents],
  );
  const taskList = liveTaskList ?? lastTaskList ?? fallbackTaskList;
  const workState = useMemo(
    () => liveEvents.length > 0
      ? getWorkState(liveEvents, connected)
      : conversationStatusToWorkState(conversationStatus, conversationLastError, connected, activeRun),
    [activeRun, connected, conversationLastError, conversationStatus, liveEvents],
  );
  const visibleRunIssue = activeRun?.status === "failed"
    ? activeRun.error || "本轮 Agent 执行失败"
    : "";
  const visibleRunIssueSummary = shortContent(visibleRunIssue, 220);
  const runIssueId = activeRun ? `${activeRun.run_id}:${activeRun.status}:${activeRun.updated_at}` : "";
  const shouldShowRunIssue = Boolean(visibleRunIssue && !ignoredRunIssueIds.has(runIssueId));
  const visibleEvents = useMemo(() => displayEvents.slice(visibleStart), [displayEvents, visibleStart]);
  const visibleSystemDetails = useMemo(() => {
    const details = visibleEvents.filter((event) => isSystemStatusEvent(event) || isToolStatusEvent(event));
    if (!activeRun?.tool_calls.length) return details;
    const liveCallIds = new Set(
      details
        .filter(isToolStatusEvent)
        .map((event) => event.tool?.call_id)
        .filter((callId): callId is string => Boolean(callId)),
    );
    const restored = activeRun.tool_calls
      .filter((tool) => !tool.call_id || !liveCallIds.has(tool.call_id))
      .map((tool) => runToolEvent(tool, activeRun.conversation_id));
    return [...details, ...restored];
  }, [activeRun, visibleEvents]);
  const notifyWorkspaceChanged = useCallback(async (notice: WorkspaceChangeNotice) => {
    if (!onWorkspaceChanged || notifiedChangeSetsRef.current.has(notice.changeSetId)) return;
    notifiedChangeSetsRef.current.add(notice.changeSetId);
    try {
      await onWorkspaceChanged(notice);
    } catch {
      notifiedChangeSetsRef.current.delete(notice.changeSetId);
    }
  }, [onWorkspaceChanged]);

  useEffect(() => {
    for (const event of events) {
      const notice = appliedWorkspaceChange(event);
      if (notice) void notifyWorkspaceChanged(notice);
    }
  }, [events, notifyWorkspaceChanged]);
  const allToolsEnabled = selectedTools === null;
  const enabledToolCount = allToolsEnabled ? tools.length : selectedTools.length;
  const consistencyToolAvailable = tools.some((tool) => tool.name === CONSISTENCY_TOOL_NAME);
  const fileChangeProposalAvailable = tools.some((tool) => tool.name === FILE_CHANGE_PROPOSAL_TOOL_NAME);
  const effectiveSelectedTools = useMemo(() => {
    if (consistencyCheckEnabled || !consistencyToolAvailable) return selectedTools;
    const names = selectedTools ?? tools.map((tool) => tool.name);
    return names.filter((name) => name !== CONSISTENCY_TOOL_NAME);
  }, [consistencyCheckEnabled, consistencyToolAvailable, selectedTools, tools]);
  const effectiveEnabledToolCount = effectiveSelectedTools === null ? tools.length : effectiveSelectedTools.length;
  const runSettled = Boolean(activeRun && activeRun.status !== "running");
  const agentBusy = activeRun?.status === "running" || (conversationStatus === "running" && !runSettled);
  const canSend = Boolean(input.trim() && connected && effectiveEnabledToolCount > 0 && !agentBusy);
  const quoteSummary = useMemo(() => summarizeQuoteReferences(quoteReferences), [quoteReferences]);
  const visibleSelectableIndexes = useMemo(
    () => visibleEvents
      .map((event, index) => ({ event, index: visibleStart + index }))
      .filter(({ event }) => isSelectableMessage(event))
      .map(({ index }) => index),
    [visibleEvents, visibleStart],
  );
  const selectedMessages = useMemo(
    () => [...selectedMessageIndexes]
      .sort((a, b) => a - b)
      .map((index) => displayEvents[index])
      .filter(Boolean)
      .filter(isSelectableMessage),
    [displayEvents, selectedMessageIndexes],
  );
  const submittedChoiceResponses = useMemo(() => {
    const responses = new Map<string, ChoiceResponse>();
    for (const event of displayEvents) {
      const response = parseChoiceResponse(event);
      if (response) responses.set(response.request_id, response);
    }
    return responses;
  }, [displayEvents]);
  const toolSummary = allToolsEnabled
    ? "全部工具"
    : enabledToolCount === 0
      ? "未选择工具"
      : selectedTools.slice(0, 2).join(", ") + (enabledToolCount > 2 ? ` +${enabledToolCount - 2}` : "");
  const toolButtonLabel = `工具 ${effectiveEnabledToolCount}/${tools.length}${consistencyToolAvailable && !consistencyCheckEnabled ? " · 跳过审查" : ""}`;
  const activeRunSummaryItems = runSummaryItems(activeRun);
  const recoverySuggestion = runRecoverySuggestion(activeRun);
  const showRunRecoveryActions = Boolean(activeRun && activeRun.status !== "running");

  const scrollMessagesToBottom = () => {
    const container = messagesRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
    bottomRef.current?.scrollIntoView({ block: "end" });
  };

  useEffect(() => {
    const start = Math.max(0, displayEvents.length - INITIAL_HISTORY_WINDOW);
    stickToBottomRef.current = true;
    pendingScrollTargetRef.current = "bottom";
    setLiveStart(displayEvents.length);
    setVisibleStart(start);
    setQuoteReferences([]);
    setChoiceSelections({});
    setLastTaskList(null);
    scrollMessagesToBottom();
    const frame = window.requestAnimationFrame(scrollMessagesToBottom);
    return () => window.cancelAnimationFrame(frame);
  }, [historyVersion]);

  useEffect(() => {
    if (liveTaskList) setLastTaskList(liveTaskList);
  }, [liveTaskList]);

  useEffect(() => {
    setVisibleStart((current) => {
      const maxStart = Math.max(0, displayEvents.length - INITIAL_HISTORY_WINDOW);
      if (stickToBottomRef.current) {
        pendingScrollTargetRef.current = "bottom";
        return maxStart;
      }
      return Math.min(current, maxStart);
    });
  }, [displayEvents.length]);

  useLayoutEffect(() => {
    const target = pendingScrollTargetRef.current;
    if (!target) return;
    const container = messagesRef.current;
    if (!container) return;
    if (target === "top") {
      container.scrollTop = 0;
    } else {
      scrollMessagesToBottom();
    }
    pendingScrollTargetRef.current = null;
  }, [visibleEvents.length, visibleStart]);

  useEffect(() => {
    setSelectedTools((current) => {
      if (current === null) return null;
      const available = new Set(tools.map((tool) => tool.name));
      const filtered = current.filter((name) => available.has(name));
      if (
        available.has(FILE_CHANGE_PROPOSAL_TOOL_NAME) &&
        !filtered.includes(FILE_CHANGE_PROPOSAL_TOOL_NAME) &&
        filtered.some((name) => EDITING_TOOL_NAMES.has(name))
      ) {
        filtered.push(FILE_CHANGE_PROPOSAL_TOOL_NAME);
      }
      if (filtered.length > 0 && filtered.length === tools.length) return null;
      return filtered;
    });
  }, [tools]);

  useEffect(() => {
    setSelectedMessageIndexes((current) => {
      const next = new Set<number>();
      for (const index of current) {
        if (isSelectableMessage(displayEvents[index])) next.add(index);
      }
      return next;
    });
  }, [displayEvents]);

  const sendMessage = (content: string) => {
    if (canSend) {
      stickToBottomRef.current = true;
      pendingScrollTargetRef.current = "bottom";
      onSend(content.trim(), effectiveSelectedTools, {
        modelContent: buildModelMessageWithReferences(content, quoteReferences),
        metadata: {
          quote_reference_count: quoteSummary.messageCount,
          quote_reference_lines: quoteSummary.lineCount,
          auto_apply_file_changes: autoApplyFileChanges,
        },
      });
      onInputChange("");
      setQuoteReferences([]);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) sendMessage(input);
    }
  };

  const handleSend = () => {
    if (canSend) sendMessage(input);
  };

  const handleScroll = () => {
    const container = messagesRef.current;
    if (!container) return;
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    stickToBottomRef.current = distanceToBottom <= BOTTOM_STICKY_DISTANCE;
  };

  const loadEarlierMessages = () => {
    pendingScrollTargetRef.current = "top";
    stickToBottomRef.current = false;
    setVisibleStart((current) => Math.max(0, current - HISTORY_PAGE_STEP));
  };

  const toggleAllTools = (checked: boolean) => {
    setSelectedTools(checked ? null : tools.map((tool) => tool.name));
  };

  const toggleTool = (name: string, checked: boolean) => {
    setSelectedTools((current) => {
      const base = current ?? tools.map((tool) => tool.name);
      return checked ? Array.from(new Set([...base, name])) : base.filter((toolName) => toolName !== name);
    });
  };

  const selectEveryTool = () => {
    setSelectedTools(tools.map((tool) => tool.name));
  };

  const selectNoTools = () => {
    setSelectedTools([]);
  };

  const toggleMessageSelection = (index: number) => {
    setSelectedMessageIndexes((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const selectVisibleMessages = () => {
    setSelectionMode(true);
    setSelectedMessageIndexes((current) => new Set([...current, ...visibleSelectableIndexes]));
  };

  const clearSelectedMessages = () => {
    setSelectedMessageIndexes(new Set());
  };

  const copySelectedMessages = async () => {
    const content = formatSelectedMessages(selectedMessages);
    if (!content) return;
    await navigator.clipboard.writeText(content);
  };

  const copyRunError = async () => {
    const parts = [
      activeRun?.error || conversationLastError || "",
      activeRun ? runErrorDetailText(activeRun) : "",
      recoverySuggestion,
    ].filter(Boolean);
    const text = parts.join("\n");
    if (text) await navigator.clipboard.writeText(text);
  };

  const ignoreRunIssue = () => {
    if (!runIssueId) return;
    setIgnoredRunIssueIds((current) => {
      const next = new Set(current);
      next.add(runIssueId);
      writeIgnoredRunIssueIds(next);
      return next;
    });
  };

  const markRunHandled = () => {
    ignoreRunIssue();
    setTaskDetailsOpen(false);
  };

  const renderRunRecovery = (run: AgentRunRecord) => {
    if (!showRunRecoveryActions) return null;
    const detail = runErrorDetailText(run);
    return (
      <div className="chat-run-recovery">
        {recoverySuggestion && <p>{recoverySuggestion}</p>}
        {detail && <p>{detail}</p>}
        <div className="chat-run-recovery-actions">
          {run.input_preview && onRetryRun && (
            <button className="btn-secondary" onClick={() => onRetryRun(run.run_id)} disabled={!connected}>
              {retryActionLabel(run)}
            </button>
          )}
          {(run.error || detail) && (
            <button className="btn-ghost" onClick={() => void copyRunError()}>
              复制错误
            </button>
          )}
          <button className="btn-ghost" onClick={markRunHandled}>
            标记已处理
          </button>
        </div>
      </div>
    );
  };

  const quoteSelectedIntoInput = () => {
    const references = quoteReferencesFromEvents(selectedMessages);
    if (!references.length) return;
    setQuoteReferences(references);
  };

  const copySingleMessage = async (event: AgentEvent) => {
    if (!event.content?.trim()) return;
    await navigator.clipboard.writeText(`${messageRoleLabel(event)}：\n${event.content.trim()}`);
  };

  const quoteSingleMessage = (event: AgentEvent) => {
    if (!event.content?.trim()) return;
    setQuoteReferences(quoteReferencesFromEvents([event]));
  };

  const updateChoiceSelection = (request: ChoiceRequest, group: ChoiceGroup, optionId: string) => {
    setChoiceSelections((current) => {
      const requestSelections = current[request.requestId] ?? {};
      const selected = requestSelections[group.id] ?? [];
      let nextSelected: string[];
      if (group.mode === "single") {
        nextSelected = [optionId];
      } else if (selected.includes(optionId)) {
        nextSelected = selected.filter((id) => id !== optionId);
      } else if (selected.length < group.maxSelections) {
        nextSelected = [...selected, optionId];
      } else {
        nextSelected = selected;
      }
      return {
        ...current,
        [request.requestId]: { ...requestSelections, [group.id]: nextSelected },
      };
    });
  };

  const clearChoiceGroup = (request: ChoiceRequest, group: ChoiceGroup) => {
    setChoiceSelections((current) => ({
      ...current,
      [request.requestId]: {
        ...(current[request.requestId] ?? {}),
        [group.id]: [],
      },
    }));
  };

  const submitChoiceRequest = (request: ChoiceRequest) => {
    if (!connected || agentBusy) return;
    const requestSelections = choiceSelections[request.requestId] ?? {};
    const selections: ChoiceResponseSelection[] = request.groups.map((group) => {
      const optionIds = requestSelections[group.id] ?? [];
      const options = optionIds
        .map((id) => group.options.find((option) => option.id === id))
        .filter((option): option is ChoiceOption => Boolean(option));
      return {
        group_id: group.id,
        option_ids: options.map((option) => option.id),
        labels: options.map((option) => option.label),
        values: options.map((option) => option.value),
      };
    });
    const invalid = request.groups.some((group, index) => {
      const count = selections[index].option_ids.length;
      return count < group.minSelections || count > group.maxSelections;
    });
    if (invalid) return;
    stickToBottomRef.current = true;
    pendingScrollTargetRef.current = "bottom";
    const lines = request.groups.map((group, index) => {
      const labels = selections[index].labels;
      return `- ${group.title}：${labels.length ? labels.join("、") : "不选择"}`;
    });
    const content = `我已完成选择：\n${lines.join("\n")}`;
    const choiceResponse: ChoiceResponse = { request_id: request.requestId, selections };
    onSend(content, effectiveSelectedTools, {
      modelContent: buildModelMessageWithReferences(content, quoteReferences),
      metadata: {
        quote_reference_count: quoteSummary.messageCount,
        quote_reference_lines: quoteSummary.lineCount,
        auto_apply_file_changes: autoApplyFileChanges,
        choice_response: choiceResponse,
      },
    });
    setQuoteReferences([]);
  };

  const renderChoiceRequest = (event: AgentEvent, eventIndex: number) => {
    const request = parseChoiceRequest(event);
    if (!request) return null;
    const submitted = submittedChoiceResponses.get(request.requestId);
    const stale = !submitted && displayEvents.slice(eventIndex + 1).some((item) => item.sender === "user");
    const requestSelections = choiceSelections[request.requestId] ?? {};
    const valid = request.groups.every((group) => {
      const count = (requestSelections[group.id] ?? []).length;
      return count >= group.minSelections && count <= group.maxSelections;
    });
    return (
      <section className={`chat-choice-request${submitted ? " is-submitted" : ""}${stale ? " is-stale" : ""}`}>
        <header className="chat-choice-request-head">
          <div>
            <strong>{request.groups.length > 1 ? "请完成以下选择" : "请选择"}</strong>
            <span>{submitted ? "已提交" : stale ? "已跳过" : `${request.groups.length} 个选择组`}</span>
          </div>
        </header>
        <div className="chat-choice-groups">
          {request.groups.map((group) => {
            const selectedIds = submitted
              ? submitted.selections.find((item) => item.group_id === group.id)?.option_ids ?? []
              : requestSelections[group.id] ?? [];
            const limitLabel = group.mode === "single"
              ? group.required ? "单选 · 必选" : "单选 · 可选"
              : `${group.required ? "多选 · 必选" : "多选 · 可选"} · ${group.minSelections}-${group.maxSelections} 项`;
            return (
              <fieldset key={group.id} className="chat-choice-group" disabled={Boolean(submitted || stale || !connected || agentBusy)}>
                <legend>
                  <strong>{group.title}</strong>
                  <span>{limitLabel}</span>
                </legend>
                {group.description && <p>{group.description}</p>}
                <div className="chat-choice-option-list">
                  {group.options.map((option) => {
                    const checked = selectedIds.includes(option.id);
                    const atLimit = group.mode === "multiple" && selectedIds.length >= group.maxSelections && !checked;
                    return (
                      <label key={option.id} className={`chat-choice-option${checked ? " is-selected" : ""}`}>
                        <input
                          type={group.mode === "single" ? "radio" : "checkbox"}
                          name={`${request.requestId}-${group.id}`}
                          checked={checked}
                          disabled={Boolean(submitted || stale || !connected || agentBusy || atLimit)}
                          onChange={() => updateChoiceSelection(request, group, option.id)}
                        />
                        <span>
                          <strong>{option.label}</strong>
                          {option.description && <small>{option.description}</small>}
                        </span>
                      </label>
                    );
                  })}
                </div>
                {!group.required && selectedIds.length > 0 && !submitted && !stale && (
                  <button className="btn-ghost chat-choice-clear" onClick={() => clearChoiceGroup(request, group)}>
                    清除此组
                  </button>
                )}
              </fieldset>
            );
          })}
        </div>
        {!submitted && !stale && (
          <footer className="chat-choice-request-actions">
            {!valid && <span>请先满足各组的选择数量要求</span>}
            <button className="btn-primary" onClick={() => submitChoiceRequest(request)} disabled={!valid || !connected || agentBusy}>
              提交选择
            </button>
          </footer>
        )}
      </section>
    );
  };

  const renderAgentContent = (event: AgentEvent, isStreaming: boolean, isLast: boolean) => {
    const hasAiRender = Boolean(event.ui_hint);
    if (hasAiRender) {
      return (
        <>
          {event.content && (
            <div className="chat-message-body">
              <MarkdownView content={event.content} />
            </div>
          )}
          <AiRender {...eventToRender(event)} compact onWorkspaceChanged={notifyWorkspaceChanged} />
        </>
      );
    }

    if (!event.content) return null;
    return (
      <div className={`chat-message-body${isStreaming && isLast ? " chat-message-body--streaming" : ""}`}>
        <MarkdownView content={event.content} />
        {isStreaming && isLast && <span className="chat-cursor" />}
      </div>
    );
  };

  const renderAgentIntervention = (event: AgentEvent) => {
    if (event.type !== "agent_final") return null;
    const raw = event.metadata?.intervention;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    const intervention = raw as {
      title?: string;
      message?: string;
      options?: Array<{ id?: string; label?: string }>;
    };
    const options = (intervention.options ?? []).filter(
      (option): option is { id: string; label: string } => Boolean(option.id && option.label),
    );
    if (!options.length) return null;
    const chooseIntervention = (id: string) => {
      if (id === "retry") {
        const runId = typeof event.metadata?.run_id === "string" ? event.metadata.run_id : activeRun?.run_id;
        if (runId) onRetryRun?.(runId);
      } else if (id === "finalize") {
        onSend("请跳过刚才失败的工具，基于已有结果直接总结本轮。", []);
      } else if (id === "clarify") {
        onContinueWithError?.(intervention.message || "请补充说明下一步应如何处理工具失败。");
      }
    };
    return (
      <div className="chat-choice-options chat-intervention-options">
        <span>{intervention.title || "请选择下一步"}</span>
        {options.map((option) => (
          <button
            key={option.id}
            className="chat-choice-option"
            onClick={() => chooseIntervention(option.id)}
            disabled={!connected}
          >
            {option.label}
          </button>
        ))}
      </div>
    );
  };

  const renderToolResult = (event: AgentEvent, eventIndex: number) => {
    const expanded = expandedToolResults.has(eventIndex);
    const title = toolResultTitle(event);
    const type = uiHintType(event);
    const summary = toolResultSummary(event);
    if (type === "changeset:proposal") {
      return (
        <section className="chat-tool-result chat-tool-result--prominent">
          <header className="chat-tool-result-prominent-head">
            <span>
              <strong>{title}</strong>
              <em>{type}</em>
            </span>
            <small>{summary}</small>
          </header>
          <div className="chat-tool-result-body">
            <AiRender {...eventToRender(event)} compact onWorkspaceChanged={notifyWorkspaceChanged} />
          </div>
        </section>
      );
    }

    return (
      <details
        className="chat-tool-result"
        open={expanded}
        onToggle={(toggleEvent) => {
          const isOpen = (toggleEvent.currentTarget as HTMLDetailsElement).open;
          setExpandedToolResults((current) => {
            const next = new Set(current);
            if (isOpen) next.add(eventIndex);
            else next.delete(eventIndex);
            return next;
          });
        }}
      >
        <summary>
          <span>
            <strong>{title}</strong>
            {type && <em>{type}</em>}
          </span>
          <small>{summary}</small>
          <span className="chat-tool-result-action" aria-hidden="true">
            {expanded ? "收起" : "展开"}
          </span>
        </summary>
        <div className="chat-tool-result-body">
          {event.ui_hint ? (
            <AiRender {...eventToRender(event)} compact onWorkspaceChanged={notifyWorkspaceChanged} />
          ) : event.content ? (
            <MarkdownView content={event.content} />
          ) : null}
        </div>
      </details>
    );
  };

  return (
    <div className="chat-panel">
      <header className="chat-header">
        <div className="chat-header-primary">
          <div className="chat-header-left">
            {onToggleConversations && (
              <button className="btn-ghost" onClick={onToggleConversations}>
                {showConversations ? "隐藏历史" : "历史"}
              </button>
            )}
            <h2>对话</h2>
          </div>
          <div className="chat-header-primary-actions">
            <div
              className={`chat-work-indicator is-${workState.kind}`}
              title={workState.label}
              aria-label={workState.label}
            >
              <span className="chat-work-indicator-icon" aria-hidden="true" />
              <span className="chat-work-indicator-text">{workState.label}</span>
            </div>
            <button
              className={selectionMode ? "btn-secondary" : "btn-ghost"}
              onClick={() => {
                setSelectionMode((value) => !value);
                if (selectionMode) clearSelectedMessages();
              }}
            >
              选择
            </button>
            <button
              className="btn-ghost chat-interrupt-button"
              onClick={onInterrupt}
              disabled={!connected}
            >
              中断
            </button>
          </div>
        </div>
        <details className="chat-header-settings">
          <summary className="chat-header-settings-summary">
            <strong>本轮设置</strong>
            <span>{toolButtonLabel}</span>
          </summary>
          <div className="chat-header-settings-body">
            <div className="chat-tool-picker">
              <button className="btn-secondary" onClick={() => setToolsOpen((value) => !value)}>
                {toolButtonLabel}
              </button>
              {toolsOpen && (
                <div className="chat-tool-menu">
                  <div className="chat-tool-summary" title={toolSummary}>
                    <span>{toolSummary}</span>
                  </div>
                  <label className="chat-tool-all">
                    <input type="checkbox" checked={allToolsEnabled} onChange={(event) => toggleAllTools(event.target.checked)} />
                    <span>全部工具</span>
                  </label>
                  {!allToolsEnabled && (
                    <div className="chat-tool-bulk">
                      <button className="btn-ghost" onClick={selectEveryTool}>全选</button>
                      <button className="btn-ghost" onClick={selectNoTools}>全不选</button>
                      <button className="btn-ghost" onClick={() => setSelectedTools(null)}>恢复默认</button>
                    </div>
                  )}
                  <div className="chat-tool-list">
                    {tools.map((tool) => (
                      <label key={tool.name} className="chat-tool-option">
                        <input
                          type="checkbox"
                          checked={allToolsEnabled || selectedTools.includes(tool.name)}
                          disabled={allToolsEnabled}
                          onChange={(event) => toggleTool(tool.name, event.target.checked)}
                        />
                        <span>
                          <strong>{tool.name}</strong>
                          <em>{tool.description}</em>
                        </span>
                      </label>
                    ))}
                    {tools.length === 0 && <p>工具列表尚未加载。</p>}
                  </div>
                </div>
              )}
            </div>
            {consistencyToolAvailable && (
              <label className="chat-consistency-toggle" title="关闭后，本轮对话不会自动调用一致性检查工具">
                <input
                  type="checkbox"
                  checked={consistencyCheckEnabled}
                  onChange={(event) => setConsistencyCheckEnabled(event.target.checked)}
                />
                <span>一致性审查</span>
              </label>
            )}
            {fileChangeProposalAvailable && (
              <label className="chat-consistency-toggle" title="开启后，Agent 生成文件改动包会自动应用；默认关闭，避免误改正式文件">
                <input
                  type="checkbox"
                  checked={autoApplyFileChanges}
                  onChange={(event) => setAutoApplyFileChanges(event.target.checked)}
                />
                <span>自动应用改动</span>
              </label>
            )}
          </div>
        </details>
      </header>

      {taskList && (
        <details
          className={`chat-task-panel${taskList.done ? " is-done" : ""}${activeRun ? " has-run" : ""}`}
          open={taskDetailsOpen}
          onToggle={(event) => setTaskDetailsOpen(event.currentTarget.open)}
        >
          <summary className="chat-task-panel-summary">
            <div className="chat-task-panel-head">
              <strong>Agent 任务</strong>
              <span>{taskList.activeLabel}</span>
              {activeRunSummaryItems.length > 0 && (
                <em>{activeRunSummaryItems.join(" · ")}</em>
              )}
            </div>
            <span className="chat-task-panel-toggle">{taskDetailsOpen ? "收起" : "详情"}</span>
          </summary>
          <div className="chat-task-panel-body">
            <ol className="chat-task-list">
              {taskList.tasks.map((task, index) => (
                <li key={`${task.label}-${index}`} className={`is-${task.status}`}>
                  <span className="chat-task-marker" aria-hidden="true" />
                  <span>{task.label}</span>
                </li>
              ))}
            </ol>
            {activeRun && (
              <div className="chat-run-report">
                <div className="chat-run-report-main">
                  <span className={`chat-run-report-status ${runStatusClass(activeRun)}`}>{runStatusLabel(activeRun)}</span>
                  <span>{activeRun.run_id}</span>
                  {activeRun.input_preview && <span>{activeRun.input_preview}</span>}
                  <span>{formatRunTime(activeRun.started_at)}{activeRun.finished_at ? ` - ${formatRunTime(activeRun.finished_at)}` : ""}</span>
                </div>
                {activeRun.tool_calls.length > 0 && (
                  <div className="chat-run-report-tools">
                    {activeRun.tool_calls.slice(-4).map((tool, index) => (
                      <span key={`${tool.name ?? "tool"}-${index}`} className={tool.status === "failed" ? "is-error" : "is-done"}>
                        {toolRunLabel(tool)}
                      </span>
                    ))}
                  </div>
                )}
                {promptAuditItems(activeRun).length > 0 && (
                  <div className="chat-run-report-audit">
                    {promptAuditItems(activeRun).map((item) => <span key={item}>{item}</span>)}
                  </div>
                )}
                {runUsageItems(activeRun).length > 0 && (
                  <div className="chat-run-report-usage">
                    {runUsageItems(activeRun).map((item) => <span key={item}>{item}</span>)}
                  </div>
                )}
                {activeRun.error && (
                  <div className="chat-run-report-error">{activeRun.error}</div>
                )}
                {renderRunRecovery(activeRun)}
              </div>
            )}
          </div>
        </details>
      )}

      {!taskList && activeRun && (
        <details
          className="chat-task-panel chat-task-panel--run-only has-run"
          open={taskDetailsOpen}
          onToggle={(event) => setTaskDetailsOpen(event.currentTarget.open)}
        >
          <summary className="chat-task-panel-summary">
            <div className="chat-task-panel-head">
              <strong>Agent 任务</strong>
              <span>{runStatusLabel(activeRun)}</span>
              {activeRunSummaryItems.length > 0 && (
                <em>{activeRunSummaryItems.join(" · ")}</em>
              )}
            </div>
            <span className="chat-task-panel-toggle">{taskDetailsOpen ? "收起" : "详情"}</span>
          </summary>
          <div className="chat-task-panel-body">
            <div className="chat-run-report">
              <div className="chat-run-report-main">
                <span className={`chat-run-report-status ${runStatusClass(activeRun)}`}>{runStatusLabel(activeRun)}</span>
                <span>{activeRun.run_id}</span>
                {activeRun.input_preview && <span>{activeRun.input_preview}</span>}
                <span>{formatRunTime(activeRun.started_at)}{activeRun.finished_at ? ` - ${formatRunTime(activeRun.finished_at)}` : ""}</span>
              </div>
              {runUsageItems(activeRun).length > 0 && (
                <div className="chat-run-report-usage">
                  {runUsageItems(activeRun).map((item) => <span key={item}>{item}</span>)}
                </div>
              )}
              {activeRun.error && (
                <div className="chat-run-report-error">{activeRun.error}</div>
              )}
              {renderRunRecovery(activeRun)}
            </div>
          </div>
        </details>
      )}

      {shouldShowRunIssue && (
        <div className="chat-run-alert">
          <div className="chat-run-alert-copy">
            <strong>{activeRun?.status === "failed" ? "Agent 执行失败" : "Agent 状态需要确认"}</strong>
            <p>{visibleRunIssueSummary}</p>
            {visibleRunIssue && (
              <details className="chat-run-alert-details">
                <summary>查看完整错误</summary>
                <pre>{visibleRunIssue}</pre>
              </details>
            )}
            {recoverySuggestion && <p>{recoverySuggestion}</p>}
            {activeRun?.input_preview && <span>上次输入：{activeRun.input_preview}</span>}
          </div>
          <div className="chat-run-alert-actions">
            {activeRun?.status === "failed" && (
              <button className="btn-ghost" onClick={() => void copyRunError()}>
                复制错误
              </button>
            )}
            {activeRun?.input_preview && onRetryRun && (
              <button
                className="btn-secondary"
                onClick={() => onRetryRun(activeRun.run_id)}
                disabled={!connected}
              >
                {retryActionLabel(activeRun)}
              </button>
            )}
            {visibleRunIssue && onContinueWithError && (
              <button className="btn-secondary" onClick={() => onContinueWithError(visibleRunIssue)} disabled={!connected}>
                带错误继续问
              </button>
            )}
            <button className="btn-ghost" onClick={markRunHandled}>
              忽略提示
            </button>
          </div>
        </div>
      )}

      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {selectionMode && (
          <div className="chat-selection-bar">
            <span>已选 {selectedMessages.length} 条</span>
            <button className="btn-ghost" onClick={selectVisibleMessages} disabled={visibleSelectableIndexes.length === 0}>
              全选可见
            </button>
            <button className="btn-ghost" onClick={copySelectedMessages} disabled={selectedMessages.length === 0}>
              复制
            </button>
            <button className="btn-ghost" onClick={quoteSelectedIntoInput} disabled={selectedMessages.length === 0}>
              引用
            </button>
            <button className="btn-ghost" onClick={clearSelectedMessages} disabled={selectedMessages.length === 0}>
              清空
            </button>
          </div>
        )}
        {displayEvents.length === 0 && (
          <div className="chat-empty">发送消息开始对话</div>
        )}
        {visibleStart > 0 && (
          <div className="chat-history-loader">
            <button className="btn-ghost" onClick={loadEarlierMessages}>
              加载更早记录
            </button>
            <span>还有 {visibleStart} 条更早消息未渲染</span>
          </div>
        )}
        {visibleSystemDetails.length > 0 && (
          <details
            className="chat-system-details"
            open={expandedSystemDetails}
            onToggle={(event) => setExpandedSystemDetails(event.currentTarget.open)}
          >
            <summary>
              <strong>运行细节</strong>
              <span>{visibleSystemDetails.length} 条状态</span>
              <em>{expandedSystemDetails ? "收起" : "展开"}</em>
            </summary>
            <div className="chat-system-details-body">
              {visibleSystemDetails.map((event, index) => (
                <span key={`${event.tool?.call_id ?? event.type}-${index}`}>
                  {isToolStatusEvent(event) ? toolStatusText(event) : systemStatusText(event)}
                </span>
              ))}
            </div>
          </details>
        )}
        {visibleEvents.map((event, i) => {
          const eventIndex = visibleStart + i;
          const isUser = event.sender === "user";
          const isSystemStatus = isSystemStatusEvent(event);
          const isError = isErrorEvent(event);
          const isToolStatus = isToolStatusEvent(event);
          const isStreaming = event.type === "stream";
          const isLast = i === visibleEvents.length - 1;
          const selectable = isSelectableMessage(event);
          const selected = selectedMessageIndexes.has(eventIndex);
          const userDisplay = isUser ? displayReferencedUserContent(event.content, event.metadata) : null;
          if (isTaskListEvent(event)) return null;
          if (isAgentRunEvent(event)) return null;
          if (isToolResultEvent(event)) {
            return (
              <div key={eventIndex} className="chat-message chat-message--tool-result">
                {renderToolResult(event, eventIndex)}
              </div>
            );
          }
          if (isSystemStatus) {
            return null;
          }
          if (isError) {
            return (
              <div key={i} className="chat-message chat-message--system is-error">
                <span>{event.content ?? "前台错误"}</span>
              </div>
            );
          }
          if (isToolStatus) {
            return null;
          }
          return (
            <div
              key={eventIndex}
              className={`chat-message ${isUser ? "chat-message--user" : "chat-message--agent"}${selected ? " is-selected" : ""}${selectionMode && selectable ? " is-selectable" : ""}`}
            >
              {selectionMode && selectable && (
                <label className="chat-message-select" title="选择这条消息">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleMessageSelection(eventIndex)}
                  />
                </label>
              )}
              {!isUser && event.type !== "stream" && (
                <div className="chat-message-type">{event.type}</div>
              )}
              {isUser && event.content && (
                <div className={`chat-message-body${isStreaming && isLast ? " chat-message-body--streaming" : ""}`}>
                  {userDisplay && userDisplay.referenceLines > 0 && (
                    <div className="chat-message-reference-summary">
                      {userDisplay.referenceCount > 1
                        ? `引用 ${userDisplay.referenceCount} 条消息 · ${userDisplay.referenceLines} 行文字`
                        : `引用 ${userDisplay.referenceLines} 行文字`}
                    </div>
                  )}
                  {userDisplay?.content ?? event.content}
                  {isStreaming && isLast && <span className="chat-cursor" />}
                </div>
              )}
              {!isUser && renderAgentContent(event, isStreaming, isLast)}
              {!isUser && <WebSourceList event={event} />}
              {!isUser && renderAgentIntervention(event)}
              {!isUser && renderChoiceRequest(event, eventIndex)}
              {selectable && (
                <div className="chat-message-actions">
                  <button className="btn-ghost" onClick={() => void copySingleMessage(event)}>复制</button>
                  <button className="btn-ghost" onClick={() => quoteSingleMessage(event)}>引用</button>
                  <button className="btn-ghost" onClick={() => toggleMessageSelection(eventIndex)}>
                    {selected ? "取消选择" : "选择"}
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
        {agentBusy && (
          <p className="chat-input-warning">Agent 正在处理当前回复，完成或中断后再发送新消息。</p>
        )}
        {effectiveEnabledToolCount === 0 && (
          <p className="chat-input-warning">至少选择一个工具，或恢复默认全部工具。</p>
        )}
        {quoteReferences.length > 0 && (
          <div className="chat-reference-box">
            <div>
              <strong>{quoteSummary.label}</strong>
            </div>
            <button className="btn-ghost" onClick={() => setQuoteReferences([])}>
              取消
            </button>
          </div>
        )}
        <div className="chat-input-row">
          <textarea
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            disabled={!connected}
          />
          <button
            className="btn-primary"
            onClick={handleSend}
            disabled={!canSend}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
