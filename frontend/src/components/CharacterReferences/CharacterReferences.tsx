import type { StoryCharacters } from "../../types";
import "./CharacterReferences.css";

interface CharacterReferencesProps {
  characters: StoryCharacters | null;
  selectedIds: string[];
  label?: string;
  readOnly?: boolean;
  disabled?: boolean;
  onChange?: (characterIds: string[]) => void;
  onOpenCharacter?: (characterId: string) => void;
}

export default function CharacterReferences({
  characters,
  selectedIds,
  label = "关联人物",
  readOnly = false,
  disabled = false,
  onChange,
  onOpenCharacter,
}: CharacterReferencesProps) {
  const activeCharacters = characters?.items ?? [];
  const archivedCharacters = characters?.archives ?? [];
  const byId = new Map<string, { name: string; archived: boolean }>();
  activeCharacters.forEach((item) => byId.set(item.character_id, { name: item.name, archived: false }));
  archivedCharacters.forEach((item) => byId.set(item.character_id, { name: item.name, archived: true }));
  const normalizedIds = Array.from(new Set(selectedIds.filter(Boolean)));
  const available = activeCharacters.filter((item) => !normalizedIds.includes(item.character_id));
  const editable = !readOnly && Boolean(onChange);

  const addCharacter = (characterId: string) => {
    if (!characterId || !onChange) return;
    onChange([...normalizedIds, characterId]);
  };

  const removeCharacter = (characterId: string) => {
    if (!onChange) return;
    onChange(normalizedIds.filter((item) => item !== characterId));
  };

  if (readOnly && normalizedIds.length === 0) return null;

  return (
    <section className={`character-references${readOnly ? " is-readonly" : ""}`}>
      <header>
        <span>{label}</span>
        <small>{normalizedIds.length > 0 ? `${normalizedIds.length} 人` : "未关联"}</small>
      </header>
      <div className="character-reference-tags">
        {normalizedIds.map((characterId) => {
          const item = byId.get(characterId);
          return (
            <span className={`character-reference-tag${item?.archived ? " is-archived" : ""}`} key={characterId}>
              <button
                type="button"
                className="character-reference-open"
                onClick={() => onOpenCharacter?.(characterId)}
                disabled={!onOpenCharacter}
                title={item?.archived ? "打开归档人物" : "打开人物档案"}
              >
                {item?.name || characterId}
              </button>
              {editable && (
                <button
                  type="button"
                  className="character-reference-remove"
                  onClick={() => removeCharacter(characterId)}
                  disabled={disabled}
                  aria-label={`移除${item?.name || characterId}`}
                  title="移除关联"
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
        {normalizedIds.length === 0 && <span className="character-reference-empty">尚未指定人物</span>}
      </div>
      {editable && (
        <select value="" onChange={(event) => addCharacter(event.target.value)} disabled={disabled || available.length === 0}>
          <option value="">{available.length > 0 ? "添加人物…" : "没有更多可选人物"}</option>
          {available.map((item) => (
            <option value={item.character_id} key={item.character_id}>
              {item.name}{item.role ? ` · ${item.role}` : ""}
            </option>
          ))}
        </select>
      )}
    </section>
  );
}
