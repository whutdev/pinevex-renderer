import { useMemo, useState } from "react";
import type { LogEntry, ProcessingStage, RenderResult } from "../types";
import { prettyJson } from "../api";
import StatusLog from "./StatusLog";
import Tabs from "./Tabs";
import ZoomableImage from "./ZoomableImage";

interface PreviewPaneProps {
  stage: ProcessingStage;
  log: LogEntry[];
  result: RenderResult | null;
  errorMessage: string | null;
  viewport: [number, number];
  transparent: boolean;
  sourceName: string;
  onRetry: () => void;
}

type TabId = "preview" | "json" | "luau" | "logs";

export default function PreviewPane(props: PreviewPaneProps) {
  const [tab, setTab] = useState<TabId>("preview");
  const { stage, result, errorMessage, viewport, transparent, sourceName, log } =
    props;

  const normalizedJson = useMemo(
    () => (result?.pinevex_object ? prettyJson(result.pinevex_object) : ""),
    [result?.pinevex_object],
  );

  const downloadPng = () => {
    if (!result?.preview) return;
    const a = document.createElement("a");
    a.href = result.preview;
    a.download = sourceName.replace(/\.json$/i, "") + ".png";
    a.click();
  };

  const copyText = (text: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
  };

  const showOverlay =
    stage === "parsing" ||
    stage === "normalizing" ||
    stage === "fetching" ||
    stage === "rendering";

  const tabs: { id: TabId; label: string; disabled?: boolean }[] = [
    { id: "preview", label: "Preview" },
    { id: "json", label: "Normalized JSON", disabled: !result },
    { id: "luau", label: "Luau", disabled: !result?.luau },
    { id: "logs", label: "Log" },
  ];

  return (
    <section className="pane pane--preview" aria-label="Render output">
      <div className="pane__header">
        <Tabs
          tabs={tabs}
          activeId={tab}
          onChange={(id) => setTab(id as TabId)}
        />
        <div className="pane__meta pane__meta--right">
          <span className="kv">
            <span className="kv__k">size</span>
            <span className="kv__v">
              {viewport[0]} × {viewport[1]}
            </span>
          </span>
          <span className="kv">
            <span className="kv__k">bg</span>
            <span className="kv__v">{transparent ? "transparent" : "white"}</span>
          </span>
          {result?.repaired ? (
            <span className="kv kv--warn">
              <span className="kv__k">repaired</span>
              <span className="kv__v">partial JSON</span>
            </span>
          ) : null}
        </div>
      </div>

      <div className="preview-body">
        {tab === "preview" ? (
          <PreviewSurface
            stage={stage}
            result={result}
            errorMessage={errorMessage}
            transparent={transparent}
            sourceName={sourceName}
            showOverlay={showOverlay}
            onRetry={props.onRetry}
            onDownload={downloadPng}
          />
        ) : null}

        {tab === "json" && result ? (
          <ReadOnlyText
            text={normalizedJson}
            onCopy={() => copyText(normalizedJson)}
            language="json"
          />
        ) : null}

        {tab === "luau" && result?.luau ? (
          <ReadOnlyText
            text={result.luau}
            onCopy={() => copyText(result.luau ?? "")}
            language="lua"
          />
        ) : null}

        {tab === "logs" ? <StatusLog log={log} stage={stage} /> : null}
      </div>
    </section>
  );
}

interface PreviewSurfaceProps {
  stage: ProcessingStage;
  result: RenderResult | null;
  errorMessage: string | null;
  transparent: boolean;
  sourceName: string;
  showOverlay: boolean;
  onRetry: () => void;
  onDownload: () => void;
}

function PreviewSurface({
  stage,
  result,
  errorMessage,
  transparent,
  sourceName,
  showOverlay,
  onRetry,
  onDownload,
}: PreviewSurfaceProps) {
  if (stage === "error") {
    return (
      <div className="surface surface--error">
        <div className="error-card">
          <span className="error-card__tag">Render error</span>
          <pre className="error-card__msg">{errorMessage ?? "Unknown error"}</pre>
          <div className="error-card__actions">
            <button className="btn btn--primary" onClick={onRetry} type="button">
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!result?.preview && stage === "idle") {
    return (
      <div className="surface surface--empty">
        <div className="empty-card">
          <h3>No render yet</h3>
          <p>
            Pick an example, paste Pinevex JSON, then press <kbd>Render</kbd>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`surface${transparent ? " surface--checker" : ""}`}
      data-source={sourceName}
    >
      {result?.preview ? (
        <ZoomableImage
          src={result.preview}
          alt={`${sourceName} render`}
        />
      ) : null}

      {showOverlay ? (
        <div className="surface__overlay">
          <div className="spinner" aria-hidden="true" />
          <span className="surface__overlay-text">{stageMessage(stage)}</span>
        </div>
      ) : null}

      {result?.preview && stage === "done" ? (
        <div className="surface__actions">
          <button className="btn btn--xs" type="button" onClick={onDownload}>
            Download PNG
          </button>
        </div>
      ) : null}
    </div>
  );
}

function stageMessage(stage: ProcessingStage): string {
  switch (stage) {
    case "parsing":
      return "Parsing source…";
    case "normalizing":
      return "Normalizing UI tree…";
    case "fetching":
      return "Fetching asset thumbnails…";
    case "rendering":
      return "Rendering PNG preview…";
    default:
      return "Working…";
  }
}

interface ReadOnlyTextProps {
  text: string;
  onCopy: () => void;
  language: string;
}

function ReadOnlyText({ text, onCopy, language }: ReadOnlyTextProps) {
  return (
    <div className="readonly">
      <div className="readonly__bar">
        <span className="readonly__lang">{language}</span>
        <span className="readonly__lines">
          {text.split("\n").length} lines · {(text.length / 1024).toFixed(1)} KB
        </span>
        <button type="button" className="btn btn--xs" onClick={onCopy}>
          Copy
        </button>
      </div>
      <pre className="readonly__pre">
        <code>{text}</code>
      </pre>
    </div>
  );
}
