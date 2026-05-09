import { useMemo, useState } from "react";
import type { VectorIndexStatus, VectorSearchResult } from "../../types";
import "./VectorPanel.css";

interface VectorPanelProps {
  status: VectorIndexStatus | null;
  results: VectorSearchResult[];
  loading: boolean;
  rebuilding: boolean;
  searching: boolean;
  error: string;
  onRefresh: () => void;
  onRebuild: () => void;
  onSearch: (query: string, collections: string[], topK: number) => void;
  onOpenFile: (path: string) => void;
}

const COLLECTION_LABELS: Record<string, string> = {
  chapters: "章节",
  characters: "角色",
  world: "世界观",
  plot: "剧情",
  other: "其他",
};

function formatNumber(value: number | undefined) {
  return new Intl.NumberFormat().format(value ?? 0);
}

function statusLabel(status: VectorIndexStatus | null) {
  if (!status) return "未知";
  if (status.status === "ready") return "可用";
  if (status.status === "stale") return "需重建";
  if (status.status === "missing") return "未建立";
  if (status.status === "invalid") return "索引损坏";
  return status.status;
}

function backendLabel(status: VectorIndexStatus | null) {
  if (!status) return "本地索引";
  if (status.backend === "chroma") return status.chroma_available ? "ChromaDB" : "ChromaDB 未就绪";
  return "本地索引";
}

export default function VectorPanel({
  status,
  results,
  loading,
  rebuilding,
  searching,
  error,
  onRefresh,
  onRebuild,
  onSearch,
  onOpenFile,
}: VectorPanelProps) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(8);
  const [selectedCollections, setSelectedCollections] = useState<string[]>([]);
  const collectionEntries = useMemo(() => Object.entries(status?.collections ?? {}).sort(), [status?.collections]);

  const toggleCollection = (collection: string) => {
    setSelectedCollections((current) => (
      current.includes(collection)
        ? current.filter((item) => item !== collection)
        : [...current, collection]
    ));
  };

  return (
    <section className="vector-panel">
      <header className="vector-header">
        <div>
          <h2>索引</h2>
          <p>{status?.index_path ?? ".aisync/vector_index.json"}</p>
        </div>
        <div className="vector-actions">
          <button className="btn-secondary" onClick={onRefresh}>刷新</button>
          <button className="btn-primary" disabled={rebuilding} onClick={onRebuild}>
            {rebuilding ? "重建中" : "重建索引"}
          </button>
        </div>
      </header>

      {loading && <p className="vector-muted">加载索引状态中…</p>}
      {error && <p className="vector-error">{error}</p>}

      {!loading && (
        <div className="vector-content">
          <section className="vector-stats">
            <div>
              <span>状态</span>
              <strong className={status?.stale ? "is-warning" : "is-success"}>{statusLabel(status)}</strong>
            </div>
            <div>
              <span>项目文件</span>
              <strong>{formatNumber(status?.files)}</strong>
            </div>
            <div>
              <span>索引文件</span>
              <strong>{formatNumber(status?.indexed_files ?? status?.files)}</strong>
            </div>
            <div>
              <span>片段</span>
              <strong>{formatNumber(status?.chunks)}</strong>
            </div>
            <div>
              <span>语义向量</span>
              <strong>{status?.embedding_model ? "已启用" : "词面兜底"}</strong>
            </div>
            <div>
              <span>向量后端</span>
              <strong>{backendLabel(status)}</strong>
            </div>
          </section>

          {status?.embedding_model && (
            <p className="vector-embedding-note">Embedding 模型：{status.embedding_model}</p>
          )}

          <section className="vector-section">
            <header>
              <h3>分组</h3>
              <span>{collectionEntries.length} 类</span>
            </header>
            <div className="vector-collections">
              {collectionEntries.length === 0 && <p className="vector-muted">暂无分组数据。</p>}
              {collectionEntries.map(([collection, count]) => (
                <button
                  key={collection}
                  className={selectedCollections.includes(collection) ? "active" : ""}
                  onClick={() => toggleCollection(collection)}
                >
                  <span>{COLLECTION_LABELS[collection] ?? collection}</span>
                  <strong>{formatNumber(count)}</strong>
                </button>
              ))}
            </div>
          </section>

          <section className="vector-section">
            <header>
              <h3>检索测试</h3>
              <span>{selectedCollections.length ? selectedCollections.join(", ") : "全部分组"}</span>
            </header>
            <div className="vector-search-row">
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入关键词或设定片段" />
              <input
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
              />
              <button className="btn-primary" disabled={searching || !query.trim()} onClick={() => onSearch(query, selectedCollections, topK)}>
                {searching ? "检索中" : "检索"}
              </button>
            </div>
            <div className="vector-results">
              {results.length === 0 && <p className="vector-muted">暂无检索结果。</p>}
              {results.map((item) => (
                <article key={item.chunk_id}>
                  <button onClick={() => onOpenFile(item.path)}>{item.path}</button>
                  <span>{COLLECTION_LABELS[item.collection] ?? item.collection} · {item.score.toFixed(4)}</span>
                  <p>{item.content.length > 260 ? `${item.content.slice(0, 260).trim()}...` : item.content}</p>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
