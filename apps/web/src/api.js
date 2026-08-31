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

async function readSse(res, onEvent) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let result = null;
  let error = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const block of parts) {
      const line = block.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      let ev;
      try {
        ev = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (ev.kind === "done") result = ev.result;
      else if (ev.kind === "error") error = ev.message || "stream error";
      else onEvent?.(ev);
    }
  }
  if (error) throw new Error(error);
  return result;
}

export const api = {
  base: BASE,
  health: () => req("/health"),
  config: () => req("/config"),
  plan: (body) => req("/plan", { method: "POST", body: JSON.stringify(body) }),
  createTrip: (body) => req("/trips", { method: "POST", body: JSON.stringify(body) }),
  /** Stream multi-agent hand-offs while a trip is planned. Falls back to POST /trips. */
  createTripLive: async (body, onEvent, signal) => {
    try {
      const res = await fetch(`${BASE}/trips/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal,
      });
      if (res.status === 404 || res.status === 405) {
        return req("/trips", { method: "POST", body: JSON.stringify(body), signal });
      }
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`${res.status} ${text}`);
      }
      if (!res.body) {
        return req("/trips", { method: "POST", body: JSON.stringify(body), signal });
      }
      const result = await readSse(res, onEvent);
      if (result) return result;
      return req("/trips", { method: "POST", body: JSON.stringify(body), signal });
    } catch (e) {
      if (signal?.aborted) throw e;
      return req("/trips", { method: "POST", body: JSON.stringify(body), signal });
    }
  },
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
  // Evaluate only THIS trip (fast, isolated) instead of the global dispatch — the client
  // never needs to evaluate everyone else's trips.
  evaluate: (tripId) => req("/monitor/evaluate", { method: "POST", body: JSON.stringify({ trip_id: tripId }) }),
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
  safeHarborsRoute: (encoded_polyline) =>
    req("/safe-harbors/route", { method: "POST", body: JSON.stringify({ encoded_polyline }) }),
  essentialsRoute: (encoded_polyline) =>
    req("/essentials/route", { method: "POST", body: JSON.stringify({ encoded_polyline }) }),
  pedestrianRoute: (encoded_polyline) =>
    req("/pedestrian/route", { method: "POST", body: JSON.stringify({ encoded_polyline }) }),
  reportIncident: (body) =>
    req("/incidents", { method: "POST", body: JSON.stringify(body) }),
  triageReport: (text, lat, lng, source = "crowd") =>
    req("/incidents/triage", { method: "POST", body: JSON.stringify({ text, lat, lng, source }) }),
  tts: (text, signal) => req("/tts", { method: "POST", body: JSON.stringify({ text }), signal }),
  resetDemo: () => req("/demo/reset", { method: "POST" }),
  webAdvisories: (body) =>
    req("/web-advisories", { method: "POST", body: JSON.stringify(body) }),
  mobility: (lat, lng, dlat, dlng) =>
    req(`/mobility?lat=${lat}&lng=${lng}` + (dlat != null ? `&dlat=${dlat}&dlng=${dlng}` : "")),
  chat: (message, session_id = "web", trip_id = "") =>
    req("/agent/chat", { method: "POST", body: JSON.stringify({ message, session_id, trip_id }) }),
};
