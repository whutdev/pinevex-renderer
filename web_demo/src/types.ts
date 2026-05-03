export type ProcessingStage =
  | "idle"
  | "drag-over"
  | "parsing"
  | "normalizing"
  | "fetching"
  | "rendering"
  | "done"
  | "error";

export interface LogEntry {
  ts: number;
  stage: ProcessingStage;
  message: string;
}

export interface RenderResult {
  ok: boolean;
  complete: boolean;
  repaired: boolean;
  pinevex_object: string;
  preview?: string | null;
  luau?: string | null;
}

export interface ParseRbxmResult {
  ok: boolean;
  source_name: string;
  root_type?: string;
  root_name?: string;
  node_count?: number;
  pinevex_object: string;
}

export interface ExampleSpec {
  id: string;
  label: string;
  description: string;
  jsonPath: string;
  thumbnailPath: string;
  viewport: [number, number];
}

export interface ViewportPreset {
  id: string;
  label: string;
  width: number;
  height: number;
}
