import { useState, useCallback, type DragEvent } from "react";

interface DropZoneProps {
  onFile: (file: File) => void;
  onPickClick: () => void;
}

export default function DropZone({ onFile, onPickClick }: DropZoneProps) {
  const [over, setOver] = useState(false);

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setOver(true);
  }, []);

  const onDragLeave = useCallback(() => setOver(false), []);

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setOver(false);
      const file = e.dataTransfer.files?.[0];
      if (file) onFile(file);
    },
    [onFile],
  );

  return (
    <div
      className={`dropzone${over ? " dropzone--over" : ""}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      role="button"
      tabIndex={0}
      onClick={onPickClick}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onPickClick()}
    >
      <div className="dropzone__row">
        <span className="dropzone__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18">
            <path
              d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <div className="dropzone__text">
          <strong>Drop a .rbxm or .json</strong>
          <span>or click to browse — Pinevex JSON works now, .rbxm parsing pending backend</span>
        </div>
      </div>
    </div>
  );
}
