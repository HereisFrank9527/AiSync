import { useEffect, useState } from "react";
import "./SchemaForm.css";

type JsonSchema = {
  type?: string;
  properties?: Record<string, JsonSchema & { description?: string }>;
  required?: string[];
  title?: string;
  default?: unknown;
  enum?: unknown[];
  description?: string;
};

interface SchemaFormProps {
  schema: JsonSchema;
  disabled?: boolean;
  actionsDisabled?: boolean;
  values?: Record<string, unknown> | null;
  onSubmit: (values: Record<string, unknown>) => void;
  submitLabel: string;
  secondaryLabel?: string;
  onSecondarySubmit?: (values: Record<string, unknown>) => void;
}

function initialValues(schema: JsonSchema): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(schema.properties ?? {})) {
    if (field.default !== undefined) values[key] = field.default;
    else if (field.type === "integer" || field.type === "number") values[key] = "";
    else if (field.type === "boolean") values[key] = false;
    else values[key] = "";
  }
  return values;
}

function normalizeValue(field: JsonSchema, value: unknown) {
  if (field.type === "integer") return value === "" ? undefined : parseInt(String(value), 10);
  if (field.type === "number") return value === "" ? undefined : Number(value);
  return value;
}

function humanizeKey(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function fieldLabel(key: string, field: JsonSchema, required: boolean) {
  return `${field.title ?? humanizeKey(key)}${required ? " *" : ""}`;
}

export default function SchemaForm({
  schema,
  disabled,
  actionsDisabled,
  values: externalValues,
  onSubmit,
  submitLabel,
  secondaryLabel,
  onSecondarySubmit,
}: SchemaFormProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(schema));

  useEffect(() => {
    setValues({ ...initialValues(schema), ...(externalValues ?? {}) });
  }, [externalValues, schema]);

  const required = new Set(schema.required ?? []);
  const normalized = () => {
    const data: Record<string, unknown> = {};
    for (const [key, field] of Object.entries(schema.properties ?? {})) {
      const value = normalizeValue(field, values[key]);
      if (value === undefined || value === "") {
        if (required.has(key)) data[key] = value ?? "";
        continue;
      }
      data[key] = value;
    }
    return data;
  };

  const renderField = (key: string, field: JsonSchema) => {
    const value = values[key];

    if (field.enum?.length) {
      return (
        <select
          value={String(value ?? "")}
          disabled={disabled}
          onChange={(e) => setValues((current) => ({ ...current, [key]: e.target.value }))}
        >
          {!required.has(key) && <option value="">未选择</option>}
          {field.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      );
    }

    if (field.type === "boolean") {
      return (
        <label className="schema-checkbox">
          <input
            type="checkbox"
            checked={Boolean(value)}
            disabled={disabled}
            onChange={(e) => setValues((current) => ({ ...current, [key]: e.target.checked }))}
          />
          启用
        </label>
      );
    }

    if (key === "content" || key === "profile" || field.type === "string" && String(value ?? "").length > 80) {
      return (
        <textarea
          rows={8}
          value={String(value ?? "")}
          disabled={disabled}
          onChange={(e) => setValues((current) => ({ ...current, [key]: e.target.value }))}
        />
      );
    }

    return (
      <input
        type={field.type === "integer" || field.type === "number" ? "number" : "text"}
        value={String(value ?? "")}
        disabled={disabled}
        onChange={(e) => setValues((current) => ({ ...current, [key]: e.target.value }))}
      />
    );
  };

  return (
    <form
      className="schema-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(normalized());
      }}
    >
      {Object.entries(schema.properties ?? {}).map(([key, field]) => (
        <div className="schema-field" key={key}>
          <label>{fieldLabel(key, field, required.has(key))}</label>
          {renderField(key, field)}
          {field.description && <p>{field.description}</p>}
        </div>
      ))}

      <div className="schema-actions">
        <button className="btn-primary" type="submit" disabled={disabled || actionsDisabled}>
          {submitLabel}
        </button>
        {secondaryLabel && onSecondarySubmit && (
          <button
            className="btn-secondary"
            type="button"
            disabled={disabled || actionsDisabled}
            onClick={() => onSecondarySubmit(normalized())}
          >
            {secondaryLabel}
          </button>
        )}
      </div>
    </form>
  );
}
