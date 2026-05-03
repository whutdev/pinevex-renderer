import type { ExampleSpec, ViewportPreset } from "./types";

export const EXAMPLES: ExampleSpec[] = [
  {
    id: "robuxshop",
    label: "RobuxShop",
    description: "Storefront panel with gradients, strokes, and icon refs.",
    jsonPath: "examples/robuxshop.json",
    thumbnailPath: "renders/robuxshop.png",
    viewport: [1920, 1080],
  },
  {
    id: "sls_lobby",
    label: "SLS Lobby",
    description: "Full lobby HUD. Heavy tree — exercises layout depth.",
    jsonPath: "examples/sls_lobby.json",
    thumbnailPath: "renders/sls_lobby.png",
    viewport: [1920, 1080],
  },
  {
    id: "upgrade",
    label: "Upgrade",
    description: "Upgrade card with tiered backgrounds and text fitting.",
    jsonPath: "examples/upgrade.json",
    thumbnailPath: "renders/upgrade.png",
    viewport: [1920, 1080],
  },
  {
    id: "simple",
    label: "Simple",
    description: "Two-element minimal example from the README.",
    jsonPath: "examples/simple-ui.json",
    thumbnailPath: "",
    viewport: [420, 180],
  },
];

export const VIEWPORT_PRESETS: ViewportPreset[] = [
  { id: "1080p", label: "1920 × 1080", width: 1920, height: 1080 },
  { id: "720p", label: "1280 × 720", width: 1280, height: 720 },
  { id: "ipad", label: "1024 × 768", width: 1024, height: 768 },
  { id: "phone", label: "390 × 844", width: 390, height: 844 },
];
