// DockClock driver theme — mirrors the web app's tokens (web/src/index.css + design_guidelines.md).
export const colors = {
  background: "#F7F9FB",
  surface: "#FFFFFF",
  foreground: "#0F172A",
  muted: "#F1F4F7",
  mutedForeground: "#4B5565",
  border: "#E2E7ED",
  primary: "#020617",
  primaryForeground: "#F8FAFC",
  accent: "#12A594",
  accentSoft: "#5EEAD4",
  slate100: "#F1F5F9",
  slate400: "#94A3B8",
  slate700: "#334155",
  slate900: "#0F172A",
  success: "#047857",
  successStrong: "#059669",
  successSoft: "#ECFDF5",
  successText: "#064E3B",
  successGlow: "#6EE7B7",
  warning: "#D97706",
  warningSoft: "#FFFBEB",
  warningMid: "#FEF3C7",
  warningBorder: "#FCD34D",
  warningGlow: "#FCD34D",
  warningText: "#78350F",
  info: "#0284C7",
  danger: "#EF4444",
  overlay: "rgba(2,6,23,0.55)",
};

export const fonts = {
  display: "SpaceGrotesk-600",
  displayBold: "SpaceGrotesk-700",
  body: "IBMPlexSans-400",
  bodyMedium: "IBMPlexSans-500",
  bodySemi: "IBMPlexSans-600",
  mono: "IBMPlexMono-Regular",
  monoSemi: "IBMPlexMono-SemiBold",
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 6, md: 10, lg: 14, xl: 16, xxl: 20, pill: 9999 };

export type Colors = typeof colors;
export function useTheme() {
  return { colors, fonts, spacing, radius };
}
