export type UiHint = Record<string, unknown> | null | undefined;

export interface AiRenderProps {
  content?: string;
  uiHint?: UiHint;
  metadata?: Record<string, unknown>;
  compact?: boolean;
}
