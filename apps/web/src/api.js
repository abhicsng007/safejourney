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
  geoSearch: (q, lat, lng) =>
    req(`/geocode/search?q=${encodeURIComponent(q)}` + (lat != null ? `&lat=${lat}&lng=${lng}` : "")),
  geoResolve: (placeId) => req(`/geocode/resolve?place_id=${encodeURIComponent(placeId)}`),
  geoReverse: (lat, lng) => req(`/geocode/reverse?lat=${lat}&lng=${lng}`),
  safeHarbors: (lat, lng) => req(`/safe-harbors?lat=${lat}&lng=${lng}`),
  essentials: (lat, lng) => req(`/essentials?lat=${lat}&lng=${lng}`),
  reportIncident: (body) =>
    req("/incidents", { method: "POST", body: JSON.stringify(body) }),
  webAdvisories: (body) =>
    req("/web-advisories", { method: "POST", body: JSON.stringify(body) }),
  mobility: (lat, lng, dlat, dlng) =>
    req(`/mobility?lat=${lat}&lng=${lng}` + (dlat != null ? `&dlat=${dlat}&dlng=${dlng}` : "")),
  chat: (message, session_id = "web", trip_id = "") =>
    req("/agent/chat", { method: "POST", body: JSON.stringify({ message, session_id, trip_id }) }),
};
