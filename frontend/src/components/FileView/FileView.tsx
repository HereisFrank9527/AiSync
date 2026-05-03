import { useEffect, useState } from "react";
import MarkdownEditor from "../MarkdownEditor";
import "./FileView.css";

interface FileViewProps {
  path: string | null;
  content: string;
  onChange: (value: string) => void;
  onSave: () => void;
  saving?: boolean;
}

export default function FileView({ path, content, onChange, onSave, saving = false }: FileViewProps) {
  const [draft, setDraft] = useState(content);

  useEffect(() => {
    setDraft(content);
  }, [content, path]);

  if (!path) {
    return <div className="file-view-empty">选择一个 Markdown 文件开始编辑</div>;
  }

  return (
    <section className="file-view">
      <header className="file-view-header">
        <div>
          <h2>{path.split(/[\\/]/).pop()}</h2>
          <p>{path}</p>
        </div>
        <button className="btn-primary" onClick={onSave} disabled={saving}>
          {saving ? "保存中…" : "保存"}
        </button>
      </header>
      <div className="file-view-editor">
        <MarkdownEditor
          value={draft}
          onChange={(value) => {
            setDraft(value);
            onChange(value);
          }}
        />
      </div>
    </section>
  );
}
