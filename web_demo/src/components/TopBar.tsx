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
        <a
          className="btn btn--ghost btn--icon"
          href="https://github.com/whutdev/pinevex-renderer"
          target="_blank"
          rel="noopener noreferrer"
          title="View Pinevex Renderer on GitHub"
        >
          <svg
            viewBox="0 0 16 16"
            width="14"
            height="14"
            aria-hidden="true"
            fill="currentColor"
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
          </svg>
          <span>GitHub</span>
        </a>
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
