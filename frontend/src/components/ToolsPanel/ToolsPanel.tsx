import { useMemo, useState } from "react";
import type { ToolDescriptor, ToolRunRecord } from "../../types";
import "./ToolsPanel.css";

interface ToolsPanelProps {
  tools: ToolDescriptor[];
  runs: ToolRunRecord[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onSelect: (tool: ToolDescriptor) => void;
  onSelectRun: (run: ToolRunRecord) => void;
  onReuseRun: (run: ToolRunRecord) => void;
}

const categoryLabels: Record<string, string> = {
  chapter: "章节写作",
  character: "角色档案",
  world: "世界设定",
  search: "资料分析",
  analysis: "分析校验",
  other: "通用能力",
};

const statusLabels: Record<ToolRunRecord["status"], string> = {
  completed: "完成",
  failed: "失败",
};

function toolCategory(tool: ToolDescriptor) {
  const name = tool.name.toLowerCase();
  const presentation = tool.presentation?.type ?? "";
  if (name.includes("chapter")) return "chapter";
  if (name.includes("character") || presentation.includes("character")) return "character";
  if (name.includes("world") || presentation.includes("worldview")) return "world";
  if (name.includes("search") || presentation.includes("search")) return "search";
  if (name.includes("consistency") || presentation.includes("issues")) return "analysis";
  return "other";
}

function accessCounts(tool: ToolDescriptor) {
  const { read, write, generate } = tool.file_access;
  return { read: read.length, write: write.length, generate: generate.length };
}

function accessSummary(tool: ToolDescriptor) {
  const counts = accessCounts(tool);
  const parts = [
    counts.read ? `读 ${counts.read}` : "",
    counts.write ? `改 ${counts.write}` : "",
    counts.generate ? `生成 ${counts.generate}` : "",
  ].filter(Boolean);
  return parts.join(" / ") || "无文件声明";
}

function shortPresentation(tool: ToolDescriptor) {
  if (!tool.presentation) return "未声明呈现";
  return tool.presentation.description || tool.presentation.type;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return date.toLocaleString();
}

export default function ToolsPanel({ tools, runs, loading, error, onRefresh, onSelect, onSelectRun, onReuseRun }: ToolsPanelProps) {
  const [toolQuery, setToolQuery] = useState("");
  const [runToolFilter, setRunToolFilter] = useState("all");
  const [runStatusFilter, setRunStatusFilter] = useState<"all" | ToolRunRecord["status"]>("all");
  const visibleTools = tools.filter((tool) => {
    const normalized = toolQuery.trim().toLowerCase();
    if (!normalized) return true;
    return `${tool.name}\n${tool.description}\n${tool.default_preset_id ?? ""}\n${tool.presentation?.type ?? ""}`.toLowerCase().includes(normalized);
  });
  const groupedTools = visibleTools.reduce<Record<string, ToolDescriptor[]>>((groups, tool) => {
    const category = toolCategory(tool);
    groups[category] = [...(groups[category] ?? []), tool];
    return groups;
  }, {});
  const totalAccess = tools.reduce(
    (acc, tool) => {
      const counts = accessCounts(tool);
      return {
        read: acc.read + counts.read,
        write: acc.write + counts.write,
        generate: acc.generate + counts.generate,
      };
    },
    { read: 0, write: 0, generate: 0 },
  );
  const completedRuns = runs.filter((run) => run.status === "completed").length;
  const runToolOptions = useMemo(() => Array.from(new Set(runs.map((run) => run.tool_name))).sort(), [runs]);
  const visibleRuns = runs.filter((run) => {
    if (runToolFilter !== "all" && run.tool_name !== runToolFilter) return false;
    if (runStatusFilter !== "all" && run.status !== runStatusFilter) return false;
    return true;
  });

  return (
    <section className="tools-panel">
      <header className="tools-header">
        <div>
          <h2>工具中心</h2>
          <p>把后端工具作为完整创作能力使用：先看文件影响，再选择直接执行或交给 Agent 生成。</p>
        </div>
        <div className="tools-header-side">
          <button className="btn-secondary" onClick={onRefresh}>刷新工具</button>
          <div className="tools-header-stats" aria-label="工具概览">
            <span><strong>{tools.length}</strong> 个能力</span>
            <span><strong>{runs.length}</strong> 次运行</span>
            <span><strong>{completedRuns}</strong> 次完成</span>
          </div>
        </div>
      </header>

      {loading && <p className="tools-muted">加载工具中…</p>}
      {error && <p className="tools-error">{error}</p>}
      {!loading && !error && tools.length === 0 && <p className="tools-muted">暂无工具</p>}

      <div className="tools-layout">
        <div className="tools-main">
          <section className="tools-capability-strip" aria-label="文件影响合计">
            <div>
              <span>可读取声明</span>
              <strong>{totalAccess.read}</strong>
            </div>
            <div>
              <span>可修改声明</span>
              <strong>{totalAccess.write}</strong>
            </div>
            <div>
              <span>可生成声明</span>
              <strong>{totalAccess.generate}</strong>
            </div>
          </section>

          <div className="tools-filter">
            <input value={toolQuery} onChange={(event) => setToolQuery(event.target.value)} placeholder="搜索工具名、说明或呈现类型" />
          </div>

          {visibleTools.length === 0 && <p className="tools-muted">没有匹配工具</p>}
          {Object.entries(groupedTools).map(([category, items]) => (
            <section className="tool-section" key={category}>
              <header>
                <h3>{categoryLabels[category] ?? categoryLabels.other}</h3>
                <span>{items.length} 个工具</span>
              </header>
              <div className="tools-grid">
                {items.map((tool) => (
                  <button className="tool-card" key={tool.name} onClick={() => onSelect(tool)}>
                    <div className="tool-card-top">
                      <span>{tool.name}</span>
                      <em>{tool.has_frontend_ui ? "表单" : "Agent"}</em>
                    </div>
                    <p>{tool.description}</p>
                    <div className="tool-card-meta">
                      {tool.default_preset_id && <em>默认方案: {tool.default_preset_id}</em>}
                      <em>{shortPresentation(tool)}</em>
                    </div>
                    <small>{accessSummary(tool)}</small>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>

        <aside className="tool-runs">
          <div className="tool-runs-header">
            <h3>最近运行</h3>
            <span>{visibleRuns.length}/{runs.length}</span>
          </div>
          <div className="tool-run-filters">
            <select value={runToolFilter} onChange={(event) => setRunToolFilter(event.target.value)}>
              <option value="all">全部工具</option>
              {runToolOptions.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <select
              value={runStatusFilter}
              onChange={(event) => setRunStatusFilter(event.target.value as "all" | ToolRunRecord["status"])}
            >
              <option value="all">全部状态</option>
              <option value="completed">完成</option>
              <option value="failed">失败</option>
            </select>
          </div>
          {runs.length === 0 && <p className="tools-muted">暂无运行记录</p>}
          {runs.length > 0 && visibleRuns.length === 0 && <p className="tools-muted">没有匹配记录</p>}
          {visibleRuns.map((run) => (
            <div className="tool-run-item" key={run.run_id}>
              <button className="tool-run-open" onClick={() => onSelectRun(run)}>
                <span>{run.tool_name}</span>
                <em className={run.status === "completed" ? "is-success" : "is-error"}>{statusLabels[run.status]}</em>
                <strong>{run.mode === "invoke" ? "AI 生成" : "直接执行"}</strong>
                <small>{formatTime(run.finished_at)}</small>
              </button>
              <button className="tool-run-reuse" onClick={() => onReuseRun(run)}>
                复用参数
              </button>
            </div>
          ))}
        </aside>
      </div>
    </section>
  );
}
