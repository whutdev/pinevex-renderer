import { VIEWPORT_PRESETS } from "../examples";

interface ViewportControlsProps {
  viewport: [number, number];
  onViewportChange: (v: [number, number]) => void;
  transparent: boolean;
  onTransparentChange: (v: boolean) => void;
  includeLuau: boolean;
  onIncludeLuauChange: (v: boolean) => void;
}

export default function ViewportControls({
  viewport,
  onViewportChange,
  transparent,
  onTransparentChange,
  includeLuau,
  onIncludeLuauChange,
}: ViewportControlsProps) {
  const [w, h] = viewport;
  const activePreset = VIEWPORT_PRESETS.find(
    (p) => p.width === w && p.height === h,
  );

  return (
    <div className="section section--controls">
      <div className="section__head">
        <span className="section__title">Render settings</span>
      </div>

      <div className="control-row">
        <label className="control">
          <span className="control__label">Width</span>
          <input
            type="number"
            min={64}
            max={4096}
            value={w}
            onChange={(e) =>
              onViewportChange([Math.max(1, Number(e.target.value) || 0), h])
            }
            className="input input--num"
          />
        </label>
        <label className="control">
          <span className="control__label">Height</span>
          <input
            type="number"
            min={64}
            max={4096}
            value={h}
            onChange={(e) =>
              onViewportChange([w, Math.max(1, Number(e.target.value) || 0)])
            }
            className="input input--num"
          />
        </label>
      </div>

      <div className="presets">
        {VIEWPORT_PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`preset${activePreset?.id === p.id ? " preset--active" : ""}`}
            onClick={() => onViewportChange([p.width, p.height])}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="toggles">
        <label className="toggle">
          <input
            type="checkbox"
            checked={transparent}
            onChange={(e) => onTransparentChange(e.target.checked)}
          />
          <span>Transparent background</span>
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={includeLuau}
            onChange={(e) => onIncludeLuauChange(e.target.checked)}
          />
          <span>Generate Luau export</span>
        </label>
      </div>
    </div>
  );
}
