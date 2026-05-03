import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import TopBar from "./components/TopBar";
import InputPane from "./components/InputPane";
import PreviewPane from "./components/PreviewPane";
import { EXAMPLES } from "./examples";
import { callRender, checkHealth, prettyJson } from "./api";
import type {
  ExampleSpec,
  LogEntry,
  ProcessingStage,
  RenderResult,
} from "./types";

const INITIAL_PLACEHOLDER = `{
  "type": "Frame",
  "size": [1, 0, 1, 0],
  "bg": [24, 28, 36],
  "children": []
}`;

interface RenderState {
  stage: ProcessingStage;
  log: LogEntry[];
  result: RenderResult | null;
  errorMessage: string | null;
  sourceName: string | null;
}

const INITIAL_STATE: RenderState = {
  stage: "idle",
  log: [],
  result: null,
  errorMessage: null,
  sourceName: null,
};

export default function App() {
  const [source, setSource] = useState<string>(INITIAL_PLACEHOLDER);
  const [sourceName, setSourceName] = useState<string>("untitled.json");
  const [viewport, setViewport] = useState<[number, number]>([1920, 1080]);
  const [transparent, setTransparent] = useState<boolean>(true);
  const [includeLuau, setIncludeLuau] = useState<boolean>(true);
  const [renderState, setRenderState] = useState<RenderState>(INITIAL_STATE);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    checkHealth(ac.signal).then(setHealthOk);
    const id = setInterval(() => {
      checkHealth().then(setHealthOk);
    }, 15000);
    return () => {
      ac.abort();
      clearInterval(id);
    };
  }, []);

  const renderSource = useCallback(
    async (
      sourceText: string,
      nextSourceName: string,
      nextViewport: [number, number],
      initialLog: LogEntry[] = [],
    ) => {
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;

      setRenderState({
        stage: "parsing",
        log: [
          ...initialLog,
          {
            ts: Date.now(),
            stage: "parsing",
            message: "Parsing Pinevex JSON",
          },
        ],
        result: null,
        errorMessage: null,
        sourceName: nextSourceName,
      });

      let trimmed: string;
      try {
        trimmed = sourceText.trim();
        if (!trimmed) throw new Error("Source JSON is empty");
        JSON.parse(trimmed);
      } catch (err) {
        setRenderState({
          stage: "error",
          log: [
            ...initialLog,
            {
              ts: Date.now(),
              stage: "error",
              message: `Invalid JSON: ${err instanceof Error ? err.message : String(err)}`,
            },
          ],
          result: null,
          errorMessage: err instanceof Error ? err.message : String(err),
          sourceName: nextSourceName,
        });
        return;
      }

      setRenderState((prev) => ({
        ...prev,
        stage: "rendering",
        log: [
          ...prev.log,
          { ts: Date.now(), stage: "normalizing", message: "Normalizing UI tree" },
          { ts: Date.now(), stage: "fetching", message: "Fetching asset thumbnails" },
          { ts: Date.now(), stage: "rendering", message: "Rendering PNG preview" },
        ],
      }));

      try {
        const result = await callRender({
          pinevexObject: trimmed,
          viewportSize: nextViewport,
          transparentBackground: transparent,
          includeLuau: includeLuau,
          signal: controller.signal,
        });
        setRenderState((prev) => ({
          ...prev,
          stage: "done",
          result,
          errorMessage: null,
          log: [
            ...prev.log,
            {
              ts: Date.now(),
              stage: "done",
              message: result.repaired
                ? "Rendered with partial-JSON repair"
                : "Render complete",
            },
          ],
        }));
      } catch (err) {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setRenderState((prev) => ({
          ...prev,
          stage: "error",
          errorMessage: message,
          log: [
            ...prev.log,
            { ts: Date.now(), stage: "error", message: `Render failed: ${message}` },
          ],
        }));
      }
    },
    [transparent, includeLuau],
  );

  const onLoadExample = useCallback(async (example: ExampleSpec) => {
    requestRef.current?.abort();
    const nextSourceName = `${example.id}.json`;
    const startedAt = Date.now();
    setRenderState({
      stage: "parsing",
      log: [
        {
          ts: startedAt,
          stage: "parsing",
          message: `Loading example: ${example.label}`,
        },
      ],
      result: null,
      errorMessage: null,
      sourceName: example.label,
    });
    setSourceName(nextSourceName);
    setViewport(example.viewport);

    try {
      const res = await fetch(example.jsonPath);
      if (!res.ok) throw new Error(`Failed to load fixture (${res.status})`);
      const text = await res.text();
      const formatted = prettyJson(text);
      setSource(formatted);
      await renderSource(formatted, nextSourceName, example.viewport, [
        {
          ts: startedAt,
          stage: "parsing",
          message: `Loading example: ${example.label}`,
        },
        {
          ts: Date.now(),
          stage: "parsing",
          message: `Loaded ${example.label}; rendering automatically`,
        },
      ]);
    } catch (err) {
      setRenderState((prev) => ({
        ...prev,
        stage: "error",
        errorMessage: err instanceof Error ? err.message : String(err),
        log: [
          ...prev.log,
          {
            ts: Date.now(),
            stage: "error",
            message: `Could not load example: ${err}`,
          },
        ],
      }));
    }
  }, [renderSource]);

  const onRender = useCallback(async () => {
    await renderSource(source, sourceName, viewport);
  }, [source, sourceName, viewport, renderSource]);

  const onClear = useCallback(() => {
    requestRef.current?.abort();
    setSource(INITIAL_PLACEHOLDER);
    setSourceName("untitled.json");
    setRenderState(INITIAL_STATE);
  }, []);

  const onPasteSource = useCallback((value: string) => {
    setSource(value);
    if (renderState.stage === "done" || renderState.stage === "error") {
      setRenderState((prev) => ({ ...prev, stage: "idle" }));
    }
  }, [renderState.stage]);

  const onParsedRbxm = useCallback(
    async (value: string, nextSourceName: string, nodeCount?: number) => {
      const formatted = prettyJson(value);
      setSource(formatted);
      setSourceName(nextSourceName);
      await renderSource(formatted, nextSourceName, viewport, [
        {
          ts: Date.now(),
          stage: "parsing",
          message: `Parsed ${nextSourceName}${nodeCount ? ` into ${nodeCount} UI nodes` : ""}; rendering automatically`,
        },
      ]);
    },
    [renderSource, viewport],
  );

  const exampleByName = useMemo(
    () => EXAMPLES.find((e) => `${e.id}.json` === sourceName) ?? null,
    [sourceName],
  );

  return (
    <div className="app-shell">
      <TopBar
        healthOk={healthOk}
        stage={renderState.stage}
        sourceName={sourceName}
        onRender={onRender}
        onClear={onClear}
        canRender={renderState.stage !== "rendering" && renderState.stage !== "fetching"}
      />
      <main className="workspace">
        <InputPane
          source={source}
          onChange={onPasteSource}
          examples={EXAMPLES}
          activeExampleId={exampleByName?.id ?? null}
          onLoadExample={onLoadExample}
          viewport={viewport}
          onViewportChange={setViewport}
          transparent={transparent}
          onTransparentChange={setTransparent}
          includeLuau={includeLuau}
          onIncludeLuauChange={setIncludeLuau}
          stage={renderState.stage}
          onSourceNameChange={setSourceName}
          sourceName={sourceName}
          onParsedRbxm={onParsedRbxm}
        />
        <PreviewPane
          stage={renderState.stage}
          log={renderState.log}
          result={renderState.result}
          errorMessage={renderState.errorMessage}
          viewport={viewport}
          transparent={transparent}
          sourceName={sourceName}
          onRetry={onRender}
        />
      </main>
    </div>
  );
}
