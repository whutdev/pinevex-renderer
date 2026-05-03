import type { ParseRbxmResult, RenderResult } from "./types";

interface RenderArgs {
  pinevexObject: string;
  viewportSize: [number, number];
  transparentBackground: boolean;
  includeLuau: boolean;
  signal?: AbortSignal;
}

const RENDER_ENDPOINT = "/render";
const PARSE_RBXM_ENDPOINT = "/parse-rbxm";
const HEALTH_ENDPOINT = "/health";

function parseObject(raw: string): unknown {
  return JSON.parse(raw);
}

export async function callRender(args: RenderArgs): Promise<RenderResult> {
  const body = {
    pinevex_object: parseObject(args.pinevexObject),
    include_preview: true,
    include_luau: args.includeLuau,
    viewport_size: args.viewportSize,
    transparent_background: args.transparentBackground,
  };

  const res = await fetch(RENDER_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: args.signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Renderer returned ${res.status} ${res.statusText}${text ? `: ${text}` : ""}`,
    );
  }

  return (await res.json()) as RenderResult;
}

export async function parseRbxmFile(file: File): Promise<ParseRbxmResult> {
  const body = new FormData();
  body.append("file", file);

  const res = await fetch(PARSE_RBXM_ENDPOINT, {
    method: "POST",
    body,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `RBXM parser returned ${res.status} ${res.statusText}${text ? `: ${text}` : ""}`,
    );
  }

  return (await res.json()) as ParseRbxmResult;
}

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(HEALTH_ENDPOINT, { signal });
    return res.ok;
  } catch {
    return false;
  }
}

export function prettyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
