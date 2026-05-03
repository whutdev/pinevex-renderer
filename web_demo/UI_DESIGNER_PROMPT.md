# Prompt for UI designer

Design a public web demo for Pinevex Renderer. Pinevex Renderer is a CPU-only renderer that achieves near-parity with Roblox's internal UI engine for structured Roblox-style UI JSON.

The demo should feel like an inspectable technical tool, not a marketing landing page. The first screen should let a serious engineer understand the system immediately: source UI structure on one side, rendered Roblox-style UI output on the other.

Do not copy the old archived web_hoster UI. Redesign the interface from scratch.

## Product goal

The page should prove that Pinevex Renderer can take Roblox-style UI structure and produce a high-fidelity PNG preview. It should make the renderer feel concrete, credible, and technically nontrivial.

## Core workflow

Design for two input modes:

1. Pinevex JSON mode, available now.
2. `.rbxm` upload mode, future/backend-dependent.

The ideal flow:

1. User drops a `.rbxm` file or pastes Pinevex JSON.
2. Demo shows parse/normalize/fetch/render progress.
3. Demo shows the rendered PNG preview.
4. Demo exposes tabs or panels for normalized JSON, rendered PNG, generated Luau, and logs.
5. User can copy JSON/Luau and download the PNG.

## Required UI surfaces

- Input area for drag-and-drop `.rbxm` upload.
- Code editor/paste area for Pinevex JSON.
- Render preview area with transparent-background checkerboard support.
- Viewport controls: common presets plus custom width/height.
- Toggle for transparent background.
- Toggle for including Luau output.
- Progress/status log.
- Error state with a concrete message.
- Empty state that makes the next action obvious.
- Success state showing preview, source name, render size, and available outputs.

## Visual direction

Use a clean, high-end technical interface. Prefer a neutral light background with restrained contrast, precise borders, and dense-but-readable controls. Avoid hype aesthetics, purple/blue AI gradients, giant hero copy, generic feature cards, and decorative blobs.

The strongest composition is a two-pane workspace:

- Left: input/source tree/code.
- Right: rendered preview.

Use a narrow top bar for brand/status/actions. The product should feel like a renderer/debugger tool, not a SaaS homepage.

## Example content

Use the existing rendered examples as visual anchors:

- RobuxShop render.
- SLS Lobby render.
- Upgrade render.

The examples should be available as quick-load chips/buttons, and selecting one should populate the JSON/source panel and render preview.

## Interaction states

Include these states in the design:

- Idle.
- Drag-over.
- Parsing.
- Fetching assets.
- Rendering.
- Done.
- Error.

Progress should feel concrete. Example messages:

- Parsing Roblox model.
- Finding renderable GUI subtree.
- Normalizing UI tree.
- Fetching asset thumbnails.
- Rendering PNG preview.

## Deliverables

Provide a responsive desktop-first design with a mobile fallback. Include the main workspace, all key states, and enough component detail for implementation in React/Tailwind or plain HTML/CSS/JS.

Keep copy short and concrete. Avoid explaining how to use obvious controls inside the app. Avoid emojis.
