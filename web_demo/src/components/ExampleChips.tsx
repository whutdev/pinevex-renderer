import type { ExampleSpec } from "../types";

interface ExampleChipsProps {
  examples: ExampleSpec[];
  activeId: string | null;
  onSelect: (e: ExampleSpec) => void;
}

export default function ExampleChips({
  examples,
  activeId,
  onSelect,
}: ExampleChipsProps) {
  return (
    <div className="chips">
      {examples.map((e) => (
        <button
          key={e.id}
          type="button"
          className={`chip${activeId === e.id ? " chip--active" : ""}`}
          onClick={() => onSelect(e)}
          title={e.description}
        >
          {e.thumbnailPath ? (
            <span
              className="chip__thumb"
              style={{ backgroundImage: `url(${e.thumbnailPath})` }}
              aria-hidden="true"
            />
          ) : (
            <span className="chip__thumb chip__thumb--blank" aria-hidden="true" />
          )}
          <span className="chip__text">
            <span className="chip__label">{e.label}</span>
            <span className="chip__desc">{e.description}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
