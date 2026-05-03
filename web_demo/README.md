# Pinevex Renderer web demo

A Vite + React + TypeScript front-end for the Pinevex Renderer API. The demo is
a two-pane workspace built to feel like an inspectable debugger: source on the
left, rendered PNG on the right.

This implements [`UI_DESIGNER_PROMPT.md`](UI_DESIGNER_PROMPT.md) against the
behavior contract in [`REFERENCE_CONTRACT.md`](REFERENCE_CONTRACT.md).

## Architecture

- The Vite dev server proxies `/render`, `/preview.png`, `/health`, and
  `/font-health` to the renderer FastAPI app at `http://127.0.0.1:8000`.
  Override with `RENDERER_API_URL` if your API runs elsewhere.
- `/parse-rbxm` is served by the web demo RBXM parser component. Locally it
  defaults to `http://127.0.0.1:8001`; override with `RBXM_PARSER_API_URL`.
- Example fixtures and reference renders live in `public/examples/` and
  `public/renders/` so the example chips can lazy-fetch them.
- `.rbxm` upload parses a ScreenGui or renderable GuiObject into Pinevex JSON,
  then renders automatically.

## Run locally

In one shell, start the renderer API:

```bash
# from repo root
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.index:app --reload
```

In another shell, start the web demo RBXM parser:

```bash
uvicorn api.parse_rbxm:app --port 8001 --reload
```

In another shell, start the demo:

```bash
cd web_demo
npm install
npm run dev
```

Open http://localhost:5173.

## Scripts

- `npm run dev` — Vite dev server on :5173 with the renderer proxy.
- `npm run build` — type-check then emit a production bundle to `dist/`.
- `npm run preview` — preview the production bundle.
- `npm run typecheck` — strict TS check without emit.

## Surfaces and states

- Idle, drag-over, parsing, normalizing, fetching, rendering, done, error.
- Status pill in the top bar reflects the current stage.
- Tabs: Preview, Normalized JSON, Luau, Log.
- Examples: RobuxShop, SLS Lobby, Upgrade, Simple. Selecting one renders it
  immediately.
