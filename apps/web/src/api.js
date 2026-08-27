const BASE = import.meta.env.VITE_API_URL || "http://localhost:8080";

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${text}`);
  }
  return res.json();
}

export const api = {
  base: BASE,
  health: () => req("/health"),
  config: () => req("/config"),
  plan: (body) => req("/plan", { method: "POST", body: JSON.stringify(body) }),
  createTrip: (body) => req("/trips", { method: "POST", body: JSON.stringify(body) }),
  getTrip: (id) => req(`/trips/${id}`),
  chooseRoute: (id, route) =>
    req(`/trips/${id}/choose-route`, { method: "POST", body: JSON.stringify({ route }) }),
  startTrip: (id, fcm_token = "") =>
    req(`/trips/${id}/start`, { method: "POST", body: JSON.stringify({ fcm_token }) }),
  setPosition: (id, lat, lng) =>
    req(`/trips/${id}/position`, { method: "POST", body: JSON.stringify({ lat, lng }) }),
  complete: (id) => req(`/trips/${id}/complete`, { method: "POST" }),
  alerts: (id) => req(`/trips/${id}/alerts`),
  hazards: (id) => req(`/trips/${id}/hazards`),
  tick: () => req("/monitor/tick", { method: "POST" }),
  forceHazard: (tripId, type, severity, at_fraction = 0.55) =>
    req("/demo/force-hazard", {
      method: "POST",
      body: JSON.stringify({ tripId, type, severity, at_fraction }),
    }),
  safeHarbors: (lat, lng) => req(`/safe-harbors?lat=${lat}&lng=${lng}`),
  chat: (message, session_id = "web") =>
    req("/agent/chat", { method: "POST", body: JSON.stringify({ message, session_id }) }),
};
