import { useCallback, useMemo, useRef } from "react";
import { prettyJson } from "../api";

interface JsonEditorProps {
  value: string;
  onChange: (value: string) => void;
}

export default function JsonEditor({ value, onChange }: JsonEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const lineCount = useMemo(() => value.split("\n").length, [value]);

  const onFormat = useCallback(() => {
    onChange(prettyJson(value));
  }, [value, onChange]);

  const onCopy = useCallback(() => {
    navigator.clipboard?.writeText(value).catch(() => {});
  }, [value]);

  return (
    <div className="editor">
      <div className="editor__toolbar">
        <button type="button" className="btn btn--xs" onClick={onFormat}>
          Format
        </button>
        <button type="button" className="btn btn--xs" onClick={onCopy}>
          Copy
        </button>
        <span className="editor__lines">{lineCount} lines</span>
      </div>
      <div className="editor__body">
        <div className="editor__gutter" aria-hidden="true">
          {Array.from({ length: Math.min(lineCount, 5000) }, (_, i) => (
            <span key={i}>{i + 1}</span>
          ))}
        </div>
        <textarea
          ref={textareaRef}
          className="editor__textarea"
          value={value}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Tab") {
              e.preventDefault();
              const ta = e.currentTarget;
              const start = ta.selectionStart;
              const end = ta.selectionEnd;
              const next =
                value.substring(0, start) + "  " + value.substring(end);
              onChange(next);
              requestAnimationFrame(() => {
                ta.selectionStart = ta.selectionEnd = start + 2;
              });
            }
          }}
        />
      </div>
    </div>
  );
}
