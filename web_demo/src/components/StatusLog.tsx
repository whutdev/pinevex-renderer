import type { LogEntry, ProcessingStage } from "../types";

interface StatusLogProps {
  log: LogEntry[];
  stage: ProcessingStage;
}

function fmtTime(ts: number) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

export default function StatusLog({ log, stage }: StatusLogProps) {
  if (log.length === 0) {
    return (
      <div className="log log--empty">
        <span>No activity yet. Status messages will appear here.</span>
      </div>
    );
  }
  return (
    <div className="log">
      {log.map((entry, i) => (
        <div key={i} className={`log__row log__row--${entry.stage}`}>
          <span className="log__time">{fmtTime(entry.ts)}</span>
          <span className="log__stage">{entry.stage}</span>
          <span className="log__msg">{entry.message}</span>
        </div>
      ))}
      {stage !== "idle" && stage !== "done" && stage !== "error" ? (
        <div className="log__row log__row--active">
          <span className="log__time">…</span>
          <span className="log__stage">{stage}</span>
          <span className="log__msg">in progress</span>
        </div>
      ) : null}
    </div>
  );
}
