import type { ProcessingStage } from "../types";

interface TopBarProps {
  healthOk: boolean | null;
  stage: ProcessingStage;
  sourceName: string;
  onRender: () => void;
  onClear: () => void;
  canRender: boolean;
}

const STAGE_TEXT: Record<ProcessingStage, string> = {
  idle: "Idle",
  "drag-over": "Awaiting file",
  parsing: "Parsing",
  normalizing: "Normalizing",
  fetching: "Fetching assets",
  rendering: "Rendering",
  done: "Done",
  error: "Error",
};

export default function TopBar({
  healthOk,
  stage,
  sourceName,
  onRender,
  onClear,
  canRender,
}: TopBarProps) {
  const healthLabel =
    healthOk === null ? "checking" : healthOk ? "online" : "offline";

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="brand-mark" aria-hidden="true" />
        <div className="brand-text">
          <span className="brand-name">Pinevex Renderer</span>
          <span className="brand-sub">preview workspace</span>
        </div>
      </div>

      <div className="topbar__status">
        <div
          className={`pill pill--${healthOk === null ? "neutral" : healthOk ? "ok" : "err"}`}
          title="Renderer service health (GET /health)"
        >
          <span className="pill__dot" />
          renderer · {healthLabel}
        </div>
        <div className={`pill pill--stage stage-${stage}`}>
          <span className="pill__dot" />
          {STAGE_TEXT[stage]}
        </div>
        <span className="topbar__source" title={sourceName}>
          {sourceName}
        </span>
      </div>

      <div className="topbar__actions">
        <button className="btn btn--ghost" type="button" onClick={onClear}>
          Reset
        </button>
        <button
          className="btn btn--primary"
          type="button"
          onClick={onRender}
          disabled={!canRender || healthOk === false}
          title={
            healthOk === false
              ? "Start the renderer with: uvicorn api.index:app --reload"
              : "Render the current source"
          }
        >
          Render
        </button>
      </div>
    </header>
  );
}
