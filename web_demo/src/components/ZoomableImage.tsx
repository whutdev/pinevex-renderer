import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

interface ZoomableImageProps {
  src: string;
  alt: string;
}

const MIN_SCALE = 0.05;
const MAX_SCALE = 32;
const WHEEL_SENSITIVITY = 0.0015;

interface Transform {
  scale: number;
  x: number;
  y: number;
}

const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };

function clampScale(s: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));
}

export default function ZoomableImage({ src, alt }: ZoomableImageProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const pointersRef = useRef<Map<number, { x: number; y: number }>>(new Map());
  const gestureRef = useRef<
    | { mode: "idle" }
    | {
        mode: "drag";
        pointerId: number;
        startX: number;
        startY: number;
        startTransform: Transform;
      }
    | {
        mode: "pinch";
        startCenter: { x: number; y: number };
        startDist: number;
        startTransform: Transform;
      }
  >({ mode: "idle" });

  const [transform, setTransform] = useState<Transform>(IDENTITY);
  const transformRef = useRef<Transform>(IDENTITY);
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number } | null>(
    null,
  );

  useEffect(() => {
    transformRef.current = transform;
  }, [transform]);

  const fit = useCallback(() => {
    const stage = stageRef.current;
    const img = imgRef.current;
    if (!stage || !img || !img.naturalWidth || !img.naturalHeight) {
      setTransform(IDENTITY);
      return;
    }
    const sw = stage.clientWidth;
    const sh = stage.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    if (sw === 0 || sh === 0) {
      setTransform(IDENTITY);
      return;
    }
    const margin = 0.92;
    const scale = clampScale(Math.min((sw / iw) * margin, (sh / ih) * margin, 1));
    const x = (sw - iw * scale) / 2;
    const y = (sh - ih * scale) / 2;
    setTransform({ scale, x, y });
  }, []);

  // Reset & re-fit whenever the image source changes.
  useLayoutEffect(() => {
    setTransform(IDENTITY);
    setNaturalSize(null);
  }, [src]);

  // Handle wheel zooming with cursor-anchored math. Must use a non-passive
  // listener so we can preventDefault on scroll.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = stage.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const cur = transformRef.current;
      const next = clampScale(cur.scale * Math.exp(-e.deltaY * WHEEL_SENSITIVITY));
      const factor = next / cur.scale;
      const nx = mx - factor * (mx - cur.x);
      const ny = my - factor * (my - cur.y);
      setTransform({ scale: next, x: nx, y: ny });
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, []);

  const computePointerInfo = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return null;
    const rect = stage.getBoundingClientRect();
    const points = Array.from(pointersRef.current.values()).map((p) => ({
      x: p.x - rect.left,
      y: p.y - rect.top,
    }));
    if (points.length === 0) return null;
    const cx = points.reduce((a, p) => a + p.x, 0) / points.length;
    const cy = points.reduce((a, p) => a + p.y, 0) / points.length;
    let dist = 0;
    if (points.length >= 2) {
      const dx = points[1].x - points[0].x;
      const dy = points[1].y - points[0].y;
      dist = Math.hypot(dx, dy);
    }
    return { cx, cy, dist };
  }, []);

  const recomputeGesture = useCallback(() => {
    const info = computePointerInfo();
    const cur = transformRef.current;
    const size = pointersRef.current.size;
    if (size === 1 && info) {
      const pointerId = pointersRef.current.keys().next().value as number;
      gestureRef.current = {
        mode: "drag",
        pointerId,
        startX: info.cx,
        startY: info.cy,
        startTransform: cur,
      };
    } else if (size >= 2 && info) {
      gestureRef.current = {
        mode: "pinch",
        startCenter: { x: info.cx, y: info.cy },
        startDist: info.dist || 1,
        startTransform: cur,
      };
    } else {
      gestureRef.current = { mode: "idle" };
    }
  }, [computePointerInfo]);

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0 && e.button !== 1) return;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {}
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    recomputeGesture();
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const info = computePointerInfo();
    if (!info) return;
    const g = gestureRef.current;
    if (g.mode === "drag" && pointersRef.current.size === 1) {
      setTransform({
        scale: g.startTransform.scale,
        x: g.startTransform.x + (info.cx - g.startX),
        y: g.startTransform.y + (info.cy - g.startY),
      });
    } else if (g.mode === "pinch" && pointersRef.current.size >= 2) {
      const rawScale = g.startTransform.scale * (info.dist / g.startDist);
      const newScale = clampScale(rawScale);
      const factor = newScale / g.startTransform.scale;
      const px = g.startCenter.x - g.startTransform.x;
      const py = g.startCenter.y - g.startTransform.y;
      setTransform({
        scale: newScale,
        x: info.cx - factor * px,
        y: info.cy - factor * py,
      });
    }
  };
  const endDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {}
    pointersRef.current.delete(e.pointerId);
    recomputeGesture();
  };

  const stepZoom = useCallback((delta: number) => {
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    const mx = rect.width / 2;
    const my = rect.height / 2;
    const cur = transformRef.current;
    const next = clampScale(cur.scale * delta);
    const factor = next / cur.scale;
    setTransform({
      scale: next,
      x: mx - factor * (mx - cur.x),
      y: my - factor * (my - cur.y),
    });
  }, []);

  const setExactScale = useCallback((target: number) => {
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    const mx = rect.width / 2;
    const my = rect.height / 2;
    const cur = transformRef.current;
    const next = clampScale(target);
    const factor = next / cur.scale;
    setTransform({
      scale: next,
      x: mx - factor * (mx - cur.x),
      y: my - factor * (my - cur.y),
    });
  }, []);

  const onImgLoad = useCallback(() => {
    const img = imgRef.current;
    if (!img) return;
    setNaturalSize({ w: img.naturalWidth, h: img.naturalHeight });
    fit();
  }, [fit]);

  return (
    <div className="zoom">
      <div
        ref={stageRef}
        className="zoom__stage"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={fit}
      >
        <div
          className="zoom__content"
          style={{
            transform: `translate3d(${transform.x}px, ${transform.y}px, 0) scale(${transform.scale})`,
          }}
        >
          <img
            ref={imgRef}
            src={src}
            alt={alt}
            draggable={false}
            onLoad={onImgLoad}
            onDragStart={(e) => e.preventDefault()}
          />
        </div>
      </div>

      <div className="zoom__controls" role="toolbar" aria-label="Preview zoom">
        <button
          type="button"
          className="zoom__btn"
          onClick={() => stepZoom(1 / 1.25)}
          aria-label="Zoom out"
          title="Zoom out (scroll wheel)"
        >
          -
        </button>
        <button
          type="button"
          className="zoom__readout"
          onClick={() => setExactScale(1)}
          title="Set 100%"
        >
          {Math.round(transform.scale * 100)}%
        </button>
        <button
          type="button"
          className="zoom__btn"
          onClick={() => stepZoom(1.25)}
          aria-label="Zoom in"
          title="Zoom in (scroll wheel)"
        >
          +
        </button>
        <span className="zoom__sep" aria-hidden="true" />
        <button
          type="button"
          className="zoom__btn zoom__btn--text"
          onClick={fit}
          title="Fit to view (double-click stage)"
        >
          Fit
        </button>
        {naturalSize ? (
          <span
            className="zoom__natural"
            title={`Native: ${naturalSize.w} x ${naturalSize.h}`}
          >
            {naturalSize.w}x{naturalSize.h}
          </span>
        ) : null}
      </div>
    </div>
  );
}
