import { useCallback, useRef, useState } from "react";
import type { ExampleSpec, ProcessingStage } from "../types";
import ExampleChips from "./ExampleChips";
import DropZone from "./DropZone";
import JsonEditor from "./JsonEditor";
import ViewportControls from "./ViewportControls";

interface InputPaneProps {
  source: string;
  onChange: (value: string) => void;
  examples: ExampleSpec[];
  activeExampleId: string | null;
  onLoadExample: (e: ExampleSpec) => void;
  viewport: [number, number];
  onViewportChange: (v: [number, number]) => void;
  transparent: boolean;
  onTransparentChange: (v: boolean) => void;
  includeLuau: boolean;
  onIncludeLuauChange: (v: boolean) => void;
  stage: ProcessingStage;
  sourceName: string;
  onSourceNameChange: (v: string) => void;
}

export default function InputPane(props: InputPaneProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pasteWarning, setPasteWarning] = useState<string | null>(null);

  const handleJsonFile = useCallback(
    async (file: File) => {
      const text = await file.text();
      try {
        JSON.parse(text);
        props.onChange(text);
        props.onSourceNameChange(file.name);
        setPasteWarning(null);
      } catch (err) {
        setPasteWarning(
          `${file.name} is not valid JSON: ${err instanceof Error ? err.message : err}`,
        );
      }
    },
    [props],
  );

  const onFileSelect = useCallback(
    async (file: File) => {
      const lower = file.name.toLowerCase();
      if (lower.endsWith(".rbxm") || lower.endsWith(".rbxmx")) {
        setPasteWarning(
          ".rbxm parsing is not wired in this renderer build yet. Paste Pinevex JSON or use an example.",
        );
        props.onSourceNameChange(file.name);
        return;
      }
      if (lower.endsWith(".json") || file.type.includes("json")) {
        await handleJsonFile(file);
        return;
      }
      setPasteWarning(`Unsupported file: ${file.name}. Expected .rbxm or .json.`);
    },
    [handleJsonFile, props],
  );

  return (
    <section className="pane pane--input" aria-label="Source">
      <div className="pane__header">
        <div className="pane__title">
          <span className="pane__label">Source</span>
          <input
            className="pane__name"
            value={props.sourceName}
            onChange={(e) => props.onSourceNameChange(e.target.value)}
            spellCheck={false}
          />
        </div>
        <div className="pane__meta">
          {(props.source.length / 1024).toFixed(1)} KB ·{" "}
          {props.source.split("\n").length} lines
        </div>
      </div>

      <DropZone
        onFile={onFileSelect}
        onPickClick={() => fileInputRef.current?.click()}
      />
      <input
        ref={fileInputRef}
        type="file"
        accept=".rbxm,.rbxmx,.json,application/json"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void onFileSelect(file);
          e.target.value = "";
        }}
      />

      {pasteWarning ? (
        <div className="notice notice--warn">{pasteWarning}</div>
      ) : null}

      <div className="section">
        <div className="section__head">
          <span className="section__title">Examples</span>
          <span className="section__hint">click to populate</span>
        </div>
        <ExampleChips
          examples={props.examples}
          activeId={props.activeExampleId}
          onSelect={props.onLoadExample}
        />
      </div>

      <div className="section section--editor">
        <div className="section__head">
          <span className="section__title">Pinevex JSON</span>
          <span className="section__hint">paste tree below</span>
        </div>
        <JsonEditor value={props.source} onChange={props.onChange} />
      </div>

      <ViewportControls
        viewport={props.viewport}
        onViewportChange={props.onViewportChange}
        transparent={props.transparent}
        onTransparentChange={props.onTransparentChange}
        includeLuau={props.includeLuau}
        onIncludeLuauChange={props.onIncludeLuauChange}
      />
    </section>
  );
}
