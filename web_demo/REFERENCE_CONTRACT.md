# Web demo reference contract

This is the behavior contract to preserve from the archived `web_hoster` without copying its UI.

## Inputs

Primary input:

- `.rbxm` upload, once the parser endpoint exists.

Fallback/current input:

- Pinevex JSON pasted into an editor.
- Example JSON loaded from the repo.

Optional render settings:

- Viewport width and height.
- Transparent background toggle.
- Include Luau toggle.
- Include normalized JSON toggle.

## Processing states

The demo should visibly represent these states:

- Idle: no file or JSON selected.
- Drag-over: user is dropping a file.
- Parsing: input is being read.
- Normalizing: Roblox UI tree is being converted to Pinevex JSON.
- Fetching assets: Roblox image/icon references are being resolved.
- Rendering: PNG is being generated.
- Done: preview, JSON, and optional Luau are available.
- Error: parser/render failure with a concrete message.

## Output

Required:

- Rendered PNG preview.
- Input name or example name.
- Render status/progress log.

Strongly preferred:

- Side-by-side source JSON and rendered output.
- Copy/download buttons for PNG, normalized JSON, and Luau.
- Viewport preset controls.
- Transparent-background preview on a checkerboard surface.

## Reference API shape

Current renderer JSON preview:

```http
POST /preview.png
Content-Type: application/json

{
  "pinevex_object": {},
  "viewport_size": [1920, 1080],
  "transparent_background": true
}
```

Current renderer JSON response:

```http
POST /render
Content-Type: application/json

{
  "pinevex_object": {},
  "include_preview": true,
  "include_luau": true,
  "viewport_size": [1920, 1080],
  "transparent_background": true
}
```

Archived `.rbxm` flow returned server-sent events with messages shaped like:

```json
{"status":"progress","message":"Fetching assets..."}
{"status":"done","image":"data:image/png;base64,..."}
{"status":"error","message":"..."}
```

If the `.rbxm` flow is rebuilt, keep a streamed-progress model or an equivalent progress channel.
