// Presentation helpers for hazards, severities and route ratings.

export const SEVERITY_COLOR = {
  info: "#7D9490",
  low: "#33D08C",
  moderate: "#F0B429",
  high: "#FF8A3D",
  critical: "#FF6150",
};

export const RATING_COLOR = {
  safe: "#33D08C",
  caution: "#F0B429",
  risky: "#FF8A3D",
  dangerous: "#FF6150",
};

export const ACTION_META = {
  advisory: { label: "Advisory", color: "#25C7DC" },
  reroute: { label: "Rerouted", color: "#F0B429" },
  harbor: { label: "Take shelter", color: "#FF8A3D" },
  sos: { label: "SOS", color: "#FF6150" },
  clear: { label: "All clear", color: "#33D08C" },
};

export const HAZARD_ICON = {
  flood: "🌊",
  waterlogging: "💧",
  electrocution: "⚡",
  lightning: "🌩️",
  storm: "🌬️",
  heat: "🔥",
  landslide: "⛰️",
  glof: "🏔️",
  roadwork: "🚧",
  pothole: "🕳️",
  unlit: "🌑",
  blackspot: "⚠️",
  rail_crossing: "🚂",
  accident: "💥",
  unsafe_area: "🚷",
  other: "❗",
};

export function hazardLabel(t) {
  return (t || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const DEMO_HAZARDS = [
  { type: "flood", severity: "critical", label: "Flooded underpass" },
  { type: "electrocution", severity: "critical", label: "Live wire in water" },
  { type: "lightning", severity: "high", label: "Lightning cell" },
  { type: "landslide", severity: "critical", label: "Landslide debris" },
  { type: "pothole", severity: "moderate", label: "Broken road / pit" },
];
