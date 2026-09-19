// Validated categorical palette (fixed order, never cycled/re-sorted) from
// the dataviz skill's reference palette. Light/dark variants selected by the
// same slot index to keep series identity stable across theme toggle.
export const CATEGORICAL_LIGHT = [
  "#2563eb", // blue (primary)
  "#8b5cf6", // purple
  "#14b8a6", // teal
  "#f59e0b", // amber
  "#ec4899", // pink
  "#22c55e", // green
  "#6366f1", // indigo
  "#ef4444", // red
];

export const CATEGORICAL_DARK = [
  "#5b8ff9",
  "#a78bfa",
  "#2dd4bf",
  "#fbbf24",
  "#f472b6",
  "#4ade80",
  "#818cf8",
  "#f87171",
];

export const STATUS_COLORS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

export const DELTA_UP_GOOD_LIGHT = "#006300";
export const DELTA_UP_GOOD_DARK = "#0ca30c";
export const DELTA_DOWN_BAD = "#d03b3b";

// Semantic accent tokens for KPI icon badges / insight priority chips.
// Kept separate from the categorical series palette since these carry
// meaning (risk/warning/brand) rather than just distinguishing series.
export function semanticColor(dark: boolean) {
  return {
    brand: dark ? "#5b8ff9" : "#2563eb",
    risk: dark ? "#f87171" : "#d03b3b",
    warning: dark ? "#c98500" : "#b57900",
    neutral: dark ? "#9a988e" : "#898781",
  };
}

// Small fixed cycle of semantic accent colors for KPI icon badges / section
// header dots, so a multi-KPI row or multi-chart report reads as a varied,
// purposeful color system instead of one repeated brand-blue tint. Assignment
// is purely presentational and deterministic — driven by a section's index
// in the report, never randomized and never implying any invented meaning
// beyond "this is the Nth section." The risk/warning check (see ReportCanvas
// isRiskLabel) always takes priority over this cycle where it applies.
// Colors are plain hex + a separate numeric alpha (not Tailwind's `/10`
// opacity-suffix syntax, which only works on Tailwind-known color tokens,
// not arbitrary hex strings interpolated at runtime) so callers can build
// an rgba() background themselves.
const KPI_ACCENT_LIGHT: { hex: string; alpha: number }[] = [
  { hex: "#2563eb", alpha: 0.1 }, // blue
  { hex: "#8b5cf6", alpha: 0.1 }, // purple
  { hex: "#14b8a6", alpha: 0.1 }, // teal
  { hex: "#f59e0b", alpha: 0.12 }, // amber
  { hex: "#ec4899", alpha: 0.1 }, // pink
];

const KPI_ACCENT_DARK: { hex: string; alpha: number }[] = [
  { hex: "#5b8ff9", alpha: 0.16 }, // blue
  { hex: "#a78bfa", alpha: 0.16 }, // purple
  { hex: "#2dd4bf", alpha: 0.16 }, // teal
  { hex: "#fbbf24", alpha: 0.18 }, // amber
  { hex: "#f472b6", alpha: 0.16 }, // pink
];

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Deterministic accent cycle for KPI icon badges and chart/table section
// header dots. Index into this array by the section's position (e.g. KPI
// index in the row, or chart/table index in the report) — same position
// always yields the same color across renders/exports, never randomized.
export function kpiAccentPalette(dark: boolean): { bg: string; text: string; border: string }[] {
  const src = dark ? KPI_ACCENT_DARK : KPI_ACCENT_LIGHT;
  return src.map((c) => ({
    bg: hexToRgba(c.hex, c.alpha),
    text: c.hex,
    border: c.hex,
  }));
}

export function chartChrome(dark: boolean) {
  return {
    surface: dark ? "#1a1a19" : "#fcfcfb",
    textPrimary: dark ? "#ffffff" : "#0b0b0b",
    textSecondary: dark ? "#c3c2b7" : "#52514e",
    muted: "#898781",
    gridline: dark ? "#2c2c2a" : "#e1e0d9",
    baseline: dark ? "#383835" : "#c3c2b7",
  };
}

export function categoricalPalette(dark: boolean): string[] {
  return dark ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;
}

export function sequentialBlue(dark: boolean): string[] {
  return dark
    ? ["#0f2e6b", "#123a81", "#1a4795", "#1f56ab", "#2b66c2", "#3d78e0", "#5b8ff9"]
    : ["#dbeafe", "#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#2563eb", "#1d4ed8", "#1e40af"];
}
