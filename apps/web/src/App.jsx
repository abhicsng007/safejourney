import { useEffect, useRef, useState, useCallback } from "react";
import MapView from "./components/MapView.jsx";
import { api } from "./api.js";
import { enablePush, fcmConfigured } from "./lib/fcm.js";
import { decodePolyline } from "./lib/polyline.js";
import {
  RATING_COLOR,
  ACTION_META,
  DEMO_HAZARDS,
  REPORT_TYPES,
  HAZARD_ICON,
  hazardLabel,
} from "./lib/hazards.js";

const MODES = [
  { id: "walk", ic: "🚶", label: "Walk" },
  { id: "two_wheeler", ic: "🛵", label: "2-Wheeler" },
  { id: "car", ic: "🚗", label: "Car" },
  { id: "transit", ic: "🚇", label: "Transit" },
];

const PRESETS = [
  { name: "Bengaluru · MG Road → Whitefield", o: { lat: 12.9757, lng: 77.605 }, d: { lat: 12.9698, lng: 77.75 } },
  { name: "Bengaluru · Koramangala → Airport", o: { lat: 12.9352, lng: 77.6245 }, d: { lat: 13.1986, lng: 77.7066 } },
  { name: "Uttarakhand · Rishikesh → Joshimath (GLOF basin)", o: { lat: 30.0869, lng: 78.2676 }, d: { lat: 30.5556, lng: 79.5626 } },
  { name: "Sikkim · Gangtok → Chungthang (Teesta)", o: { lat: 27.3314, lng: 88.6138 }, d: { lat: 27.6009, lng: 88.6448 } },
];

function fmtKm(m) {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}
function fmtMin(s) {
  return `${Math.round(s / 60)} min`;
}
// Format a web-report date ("2026-08-26" or "2026-08") into a short human label.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtReportDate(d) {
  const s = (d || "").trim();
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] || ""} ${m[1]}`.trim();
  m = /^(\d{4})-(\d{2})/.exec(s);
  if (m) return `${MONTHS[Number(m[2]) - 1] || ""} ${m[1]}`.trim();
  return s; // already human, or blank
}
function pointAtFraction(coords, f) {
  if (!coords.length) return null;
  const i = Math.min(coords.length - 1, Math.max(0, Math.round((coords.length - 1) * f)));
  return { lng: coords[i][0], lat: coords[i][1] };
}
function haversineM(lat1, lng1, lat2, lng2) {
  const R = 6371000, toR = Math.PI / 180;
  const dphi = (lat2 - lat1) * toR, dl = (lng2 - lng1) * toR;
  const a =
    Math.sin(dphi / 2) ** 2 +
    Math.cos(lat1 * toR) * Math.cos(lat2 * toR) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}
function fmtAhead(m) {
  if (m == null) return "";
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

export default function App() {
  const [phase, setPhase] = useState("plan"); // plan | routes | active
  const [mode, setMode] = useState("two_wheeler");
  const [presetIdx, setPresetIdx] = useState(0);
  const [origin, setOrigin] = useState(PRESETS[0].o);
  const [destination, setDestination] = useState(PRESETS[0].d);
  const [originLabel, setOriginLabel] = useState(PRESETS[0].name);
  const [destLabel, setDestLabel] = useState("Destination");
  const [setting, setSetting] = useState(null); // 'origin' | 'destination'

  const [plan, setPlan] = useState(null);
  const [prep, setPrep] = useState(null);
  const [selectedRouteId, setSelectedRouteId] = useState(null);
  const [trip, setTrip] = useState(null);
  const [gpsOn, setGpsOn] = useState(false);

  const [hazards, setHazards] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [harbors, setHarbors] = useState([]);
  const [essentials, setEssentials] = useState([]);
  const [webAdvisories, setWebAdvisories] = useState([]);
  const [webBusy, setWebBusy] = useState(false);
  const [mobility, setMobility] = useState(null);
  const [position, setPosition] = useState(null);
  const [safetyScore, setSafetyScore] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [status, setStatus] = useState({ online: null, msg: "Checking backend…" });
  const [busy, setBusy] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  const [focusPoint, setFocusPoint] = useState(null);
  const seenAlerts = useRef(new Set());
  const warnedProx = useRef(new Set());

  // health check
  useEffect(() => {
    api
      .config()
      .then((c) =>
        setStatus({ online: true, msg: `backend ok · gemini:${c.gemini_available ? "on" : "fallback"} · maps:${c.maps_key ? "on" : "fallback"}` })
      )
      .catch(() => setStatus({ online: false, msg: `no backend at ${api.base} — start agent-api` }));
  }, []);

  // Deep-link: a push click opens /?trip=<id> — jump straight into that active trip.
  useEffect(() => {
    const tripId = new URLSearchParams(window.location.search).get("trip");
    if (!tripId) return;
    (async () => {
      try {
        const t = await api.getTrip(tripId);
        setTrip(t);
        setPosition(t.current_position || t.origin);
        setPhase("active");
        await refresh(tripId, true);
        window.history.replaceState({}, "", window.location.pathname);
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedRoute =
    plan?.routes?.find((r) => r.route_id === selectedRouteId) || plan?.routes?.[0];

  const onMapClick = useCallback(
    (ll) => {
      const coordLabel = `${ll.lat.toFixed(4)}, ${ll.lng.toFixed(4)}`;
      const which = setting;
      if (which === "origin") { setOrigin(ll); setOriginLabel(coordLabel); }
      else if (which === "destination") { setDestination(ll); setDestLabel(coordLabel); }
      setSetting(null);
      setFocusPoint({ lat: ll.lat, lng: ll.lng });
      // Upgrade the coord label to a real place name in the background.
      api.geoReverse(ll.lat, ll.lng).then((d) => {
        if (!d?.label) return;
        if (which === "origin") setOriginLabel(d.label);
        else if (which === "destination") setDestLabel(d.label);
      }).catch(() => {});
    },
    [setting]
  );

  function applyPreset(i) {
    setPresetIdx(i);
    setOrigin(PRESETS[i].o);
    setDestination(PRESETS[i].d);
    setOriginLabel(PRESETS[i].name);
    setDestLabel("Destination");
    setFitKey((k) => k + 1);
  }

  const pickOrigin = useCallback((loc) => {
    setOrigin({ lat: loc.lat, lng: loc.lng });
    setOriginLabel(loc.label);
    setFocusPoint({ lat: loc.lat, lng: loc.lng }); // fly to it
  }, []);

  const pickDestination = useCallback((loc) => {
    setDestination({ lat: loc.lat, lng: loc.lng });
    setDestLabel(loc.label);
    setFocusPoint({ lat: loc.lat, lng: loc.lng }); // fly to it
  }, []);

  async function findRoute() {
    if (!origin || !destination) return;
    setBusy(true);
    try {
      const res = await api.createTrip({
        uid: "web-demo",
        origin,
        destination,
        mode,
        origin_label: originLabel || "Origin",
        destination_label: destLabel || "Destination",
      });
      setTrip(res.trip);
      setPlan(res.plan);
      setPrep(res.prep);
      setSelectedRouteId(res.plan.recommended_route_id);
      setHazards(selectedHazards(res.plan, res.plan.recommended_route_id));
      setPhase("prep");
      setFitKey((k) => k + 1);
      // Web-grounded advisories stream in after routes are shown (they take a few seconds).
      fetchWebAdvisories(res.plan);
    } catch (e) {
      pushToast("Couldn't plan route", String(e.message || e), "#ff6150");
    } finally {
      setBusy(false);
    }
  }

  function selectedHazards(p, id) {
    const r = p.routes.find((x) => x.route_id === id) || p.routes[0];
    return r ? r.hazards : [];
  }

  async function fetchWebAdvisories(p) {
    const r = p.routes?.find((x) => x.route_id === p.recommended_route_id) || p.routes?.[0];
    if (!r?.encoded_polyline) return;
    setWebAdvisories([]);
    setWebBusy(true);
    try {
      const res = await api.webAdvisories({
        origin_label: originLabel,
        destination_label: destLabel,
        encoded_polyline: r.encoded_polyline,
      });
      setWebAdvisories(res.advisories || []);
    } catch {
      setWebAdvisories([]);
    } finally {
      setWebBusy(false);
    }
  }

  async function startGuardian() {
    if (!trip || !selectedRoute) return;
    setBusy(true);
    try {
      await api.chooseRoute(trip.id, {
        encoded_polyline: selectedRoute.encoded_polyline,
        distance_m: selectedRoute.distance_m,
        duration_s: selectedRoute.duration_s,
      });
      // Register for push so alerts reach the traveller even with the app closed.
      let fcmToken = "";
      if (fcmConfigured()) {
        fcmToken = await enablePush((payload) => {
          const n = payload?.notification || payload?.data || {};
          pushToast(n.title || "SafeJourney", n.body || "Hazard ahead.", "#ff8a3d");
        });
        if (fcmToken) pushToast("Push enabled", "You'll get alerts even with the app closed.", "#33d08c");
      }
      const t = await api.startTrip(trip.id, fcmToken);
      setTrip(t);
      setPosition(t.origin);
      setAlerts([]);
      setHarbors([]);
      seenAlerts.current = new Set();
      setPhase("active");
      setFitKey((k) => k + 1);
      refresh(t.id, true);
      // Auto-show nearby refuges + supplies without a tap.
      const start = t.origin;
      findHarbor(start, true);
      findEssentials(start, true);
    } catch (e) {
      pushToast("Couldn't start", String(e.message || e), "#ff6150");
    } finally {
      setBusy(false);
    }
  }

  // active monitoring loop (client drives ticks locally; in cloud, Scheduler does this)
  useEffect(() => {
    if (phase !== "active" || !trip) return;
    let alive = true;
    const loop = async () => {
      try {
        await api.tick();
        if (alive) await refresh(trip.id);
      } catch {}
    };
    const iv = setInterval(loop, 6000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [phase, trip]);

  // Proximity alert: warn the moment the traveller comes within ~300 m of a known hazard.
  useEffect(() => {
    if (phase !== "active" || !position || !hazards.length) return;
    for (const h of hazards) {
      const key = `${h.type}:${h.lat.toFixed(4)}:${h.lng.toFixed(4)}`;
      const d = haversineM(position.lat, position.lng, h.lat, h.lng);
      if (d <= 300 && !warnedProx.current.has(key)) {
        warnedProx.current.add(key);
        pushToast(
          `${HAZARD_ICON[h.type] || "❗"} ${hazardLabel(h.type)} ~${Math.round(d)} m`,
          h.description || "Approaching a hazard — stay alert.",
          "#ff8a3d"
        );
      } else if (d > 500 && warnedProx.current.has(key)) {
        warnedProx.current.delete(key); // re-arm once well past, so a loop back re-warns
      }
    }
  }, [position, hazards, phase]);

  // Real GPS: stream the device location to the backend so monitoring watches the road
  // actually ahead of the traveller. Falls back to the simulate buttons when off/denied.
  useEffect(() => {
    if (phase !== "active" || !trip || !gpsOn) return;
    if (!("geolocation" in navigator)) {
      pushToast("No GPS", "This device has no geolocation — using simulated movement.", "#f0b429");
      setGpsOn(false);
      return;
    }
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setPosition(p);
        api.setPosition(trip.id, p.lat, p.lng).catch(() => {});
      },
      (err) => {
        pushToast("Location off", err.message || "Couldn't read your location.", "#ff6150");
        setGpsOn(false);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [phase, trip, gpsOn]);

  async function refresh(tripId, silent = false) {
    try {
      const [hz, al] = await Promise.all([api.hazards(tripId), api.alerts(tripId)]);
      setHazards(hz.hazards || []);
      if (hz.safety_score != null) setSafetyScore(hz.safety_score);
      const list = al.alerts || [];
      setAlerts(list);
      if (!silent) {
        for (const a of [...list].reverse()) {
          if (!seenAlerts.current.has(a.id)) {
            seenAlerts.current.add(a.id);
            pushToast(a.title, a.message, ACTION_META[a.action]?.color || "#25c7dc");
          }
        }
      } else {
        list.forEach((a) => seenAlerts.current.add(a.id));
      }
    } catch {}
  }

  async function injectHazard(h) {
    if (!trip) return;
    try {
      await api.forceHazard(trip.id, h.type, h.severity);
      await api.tick();
      await refresh(trip.id);
    } catch (e) {
      pushToast("Demo failed", String(e.message || e), "#ff6150");
    }
  }

  async function advance(f) {
    if (!trip) return;
    const coords = decodePolyline(trip.encoded_polyline);
    const p = pointAtFraction(coords, f);
    if (!p) return;
    setPosition(p);
    try {
      await api.setPosition(trip.id, p.lat, p.lng);
    } catch {}
  }

  async function findHarbor(point, silent = false) {
    const p = point || position;
    if (!p) return;
    try {
      const res = await api.safeHarbors(p.lat, p.lng);
      setHarbors(res.harbors || []);
      if (!silent) pushToast("Safe harbours nearby", `${res.harbors?.length || 0} refuge(s) marked on the map.`, "#f0b429");
    } catch {}
  }

  async function findMobility() {
    if (!position) return;
    try {
      const d = trip?.destination;
      const res = await api.mobility(position.lat, position.lng, d?.lat, d?.lng);
      setMobility(res);
      pushToast("Safer alternatives", `${res.options?.length || 0} cab/transit option(s) ready.`, "#25c7dc");
    } catch {}
  }

  async function reportHazard(rt) {
    const p = position;
    if (!p) {
      pushToast("No location yet", "Turn on GPS or advance so I know where the hazard is.", "#f0b429");
      return;
    }
    try {
      await api.reportIncident({
        type: rt.type,
        severity: rt.severity,
        lat: p.lat,
        lng: p.lng,
        description: `${rt.label} reported by a traveller on this road.`,
        source: "crowd",
      });
      pushToast("Thanks — reported", `${rt.label} logged. Travellers behind you will be warned.`, "#33d08c");
      // Surface it immediately on this trip too.
      await api.tick();
      if (trip) await refresh(trip.id);
    } catch (e) {
      pushToast("Report failed", String(e.message || e), "#ff6150");
    }
  }

  async function findEssentials(point, silent = false) {
    const p = point || position || origin;
    if (!p) return;
    try {
      const res = await api.essentials(p.lat, p.lng);
      setEssentials(res.essentials || []);
      if (!silent) pushToast("Essentials nearby", `${res.essentials?.length || 0} place(s) marked on the map.`, "#8ad6ff");
    } catch {}
  }

  async function arrived() {
    if (trip) await api.complete(trip.id).catch(() => {});
    setPhase("plan");
    setTrip(null);
    setPlan(null);
    setPrep(null);
    setGpsOn(false);
    setHazards([]);
    setAlerts([]);
    setHarbors([]);
    setEssentials([]);
    setWebAdvisories([]);
    setMobility(null);
    setPosition(null);
    setSafetyScore(null);
  }

  function pushToast(title, msg, color) {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, title, msg, color }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
  }

  return (
    <div className="app">
      <div className="panel">
        <div className="brand">
          <span className="beacon"><span /></span>
          <div style={{ flex: 1 }}>
            <h1>SafeJourney</h1>
            <span className="tag">agentic travel guardian</span>
          </div>
          {phase !== "plan" && (
            <button className="btn btn-ghost" style={{ padding: "8px 12px" }} onClick={arrived}>
              {phase === "active" ? "End" : "Back"}
            </button>
          )}
        </div>

        <div className="body">
          {phase === "plan" && (
            <PlanPanel
              mode={mode}
              setMode={setMode}
              presetIdx={presetIdx}
              applyPreset={applyPreset}
              setting={setting}
              setSetting={setSetting}
              origin={origin}
              destination={destination}
              originLabel={originLabel}
              destLabel={destLabel}
              pickOrigin={pickOrigin}
              pickDestination={pickDestination}
              findRoute={findRoute}
              busy={busy}
              online={status.online}
            />
          )}

          {phase === "prep" && prep && (
            <PrepPanel
              prep={prep}
              plan={plan}
              mode={mode}
              webAdvisories={webAdvisories}
              webBusy={webBusy}
              proceed={() => {
                setPhase("routes");
                setFitKey((k) => k + 1);
              }}
            />
          )}

          {phase === "routes" && plan && (
            <RoutesPanel
              plan={plan}
              selectedRouteId={selectedRouteId}
              onSelect={(id) => {
                setSelectedRouteId(id);
                setHazards(selectedHazards(plan, id));
              }}
              selectedRoute={selectedRoute}
              startGuardian={startGuardian}
              busy={busy}
              webAdvisories={webAdvisories}
              webBusy={webBusy}
            />
          )}

          {phase === "active" && (
            <ActivePanel
              trip={trip}
              alerts={alerts}
              safetyScore={safetyScore}
              injectHazard={injectHazard}
              advance={advance}
              findHarbor={findHarbor}
              findMobility={findMobility}
              findEssentials={findEssentials}
              essentials={essentials}
              reportHazard={reportHazard}
              mobility={mobility}
              gpsOn={gpsOn}
              toggleGps={() => setGpsOn((v) => !v)}
            />
          )}
        </div>

        <div className="status">
          <span className={`dot ${status.online === true ? "live" : status.online === false ? "off" : ""}`} />
          {status.msg}
        </div>
      </div>

      <MapView
        mapMode={phase === "active" ? "active" : "routes"}
        routes={phase === "routes" || phase === "prep" ? plan?.routes || [] : []}
        selectedRouteId={selectedRouteId}
        activePolyline={phase === "active" ? trip?.encoded_polyline : null}
        hazards={hazards}
        harbors={harbors}
        essentials={essentials}
        webAdvisories={phase === "prep" || phase === "routes" || phase === "active" ? webAdvisories : []}
        origin={phase !== "active" ? origin : trip?.origin}
        destination={phase !== "active" ? destination : trip?.destination}
        position={phase === "active" ? position : null}
        onMapClick={setting ? onMapClick : null}
        scanning={phase === "plan" && busy}
        fitKey={fitKey}
        focusPoint={focusPoint}
      />

      <div className="toasts">
        {toasts.map((t) => (
          <div className="toast" key={t.id} style={{ borderLeftColor: t.color }}>
            <div className="t-title">{t.title}</div>
            <div className="t-msg">{t.msg}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- panels ---------------- */

function LocationInput({ label, valueLabel, placeholder, center, onPick, allowGps }) {
  const [q, setQ] = useState(valueLabel || "");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const boxRef = useRef(null);
  const tRef = useRef(null);

  useEffect(() => {
    setQ(valueLabel || "");
  }, [valueLabel]);

  useEffect(() => {
    function onDoc(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function onChange(v) {
    setQ(v);
    clearTimeout(tRef.current);
    if (v.trim().length < 3) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    tRef.current = setTimeout(async () => {
      try {
        const res = await api.geoSearch(v.trim(), center?.lat, center?.lng);
        setResults(res.results || []);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 280);
  }

  async function pick(r) {
    setOpen(false);
    let loc = r;
    if (r.lat == null) {
      try {
        loc = await api.geoResolve(r.place_id);
      } catch {
        return;
      }
    }
    setQ(loc.label);
    onPick({ lat: loc.lat, lng: loc.lng, label: loc.label });
  }

  function useGps() {
    if (!("geolocation" in navigator)) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        let lbl = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
        try {
          const d = await api.geoReverse(lat, lng);
          lbl = d.label || lbl;
        } catch {}
        setQ(lbl);
        onPick({ lat, lng, label: lbl });
        setLocating(false);
      },
      () => setLocating(false),
      { enableHighAccuracy: true, timeout: 12000 }
    );
  }

  return (
    <div className="field loc-field" ref={boxRef}>
      <label>{label}</label>
      <div className="loc-row">
        <input
          value={q}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
        />
        {allowGps && (
          <button className="loc-gps" title="Use my location" onClick={useGps} disabled={locating}>
            {locating ? "…" : "📍"}
          </button>
        )}
        {open && results.length > 0 && (
          <div className="loc-list">
            {results.map((r, i) => (
              <button className="loc-item" key={i} onClick={() => pick(r)}>
                <span className="loc-pin">📍</span>
                <span className="loc-label">{r.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {loading && <div className="loc-loading">searching…</div>}
    </div>
  );
}

function PlanPanel({ mode, setMode, presetIdx, applyPreset, setting, setSetting, origin, destination, originLabel, destLabel, pickOrigin, pickDestination, findRoute, busy, online }) {
  return (
    <>
      <div className="hint">
        Search a start and destination, or use your location. SafeJourney checks every
        candidate route for floods, lightning, live wires, road works and upstream calamity —
        then recommends the safest.
      </div>

      <LocationInput
        label="Start"
        valueLabel={originLabel}
        placeholder="Search a place, or tap 📍 for your location"
        center={origin}
        onPick={pickOrigin}
        allowGps
      />
      <LocationInput
        label="Destination"
        valueLabel={destLabel === "Destination" ? "" : destLabel}
        placeholder="Search your destination"
        center={origin}
        onPick={pickDestination}
      />

      <div className="field">
        <span className="section-label">Or a demo journey / tap the map</span>
        <select value={presetIdx} onChange={(e) => applyPreset(Number(e.target.value))}>
          {PRESETS.map((p, i) => (
            <option value={i} key={i}>{p.name}</option>
          ))}
        </select>
        <div className="btn-row" style={{ marginTop: 8 }}>
          <button className={`btn ${setting === "origin" ? "btn-primary" : "btn-ghost"}`} onClick={() => setSetting("origin")}>
            {setting === "origin" ? "Tap map…" : "Pin start"}
          </button>
          <button className={`btn ${setting === "destination" ? "btn-primary" : "btn-ghost"}`} onClick={() => setSetting("destination")}>
            {setting === "destination" ? "Tap map…" : "Pin end"}
          </button>
        </div>
      </div>

      <div className="field">
        <label>Travel mode</label>
        <div className="modes">
          {MODES.map((m) => (
            <button key={m.id} className={`mode ${mode === m.id ? "active" : ""}`} onClick={() => setMode(m.id)}>
              <span className="ic">{m.ic}</span>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <button className="btn btn-primary" onClick={findRoute} disabled={busy || online === false}>
        {busy ? "Scanning routes…" : "Find the safest route"}
      </button>
      {online === false && (
        <div className="hint" style={{ color: "#ffb3aa" }}>
          Backend not reachable. Start it with <span className="mono">uvicorn main:app --port 8080</span>.
        </div>
      )}
    </>
  );
}

function AgentNote({ agent }) {
  if (!agent) return null;
  return (
    <>
      {agent.summary && (
        <div className="agent-note">
          <div className="a-head">
            <span className="beacon" style={{ transform: "scale(0.7)" }}><span /></span>
            Guardian reasoning
          </div>
          <div className="a-body">{agent.summary}</div>
        </div>
      )}
      {agent.provenance?.length > 0 && (
        <div className="provenance">
          <span className="pv-label">grounded by</span>
          {agent.provenance.map((s) => (
            <span className="chip" key={s}>{s}</span>
          ))}
        </div>
      )}
    </>
  );
}

function WebAdvisoriesBlock({ webAdvisories, webBusy }) {
  if (!webBusy && (!webAdvisories || webAdvisories.length === 0)) return null;
  return (
    <>
      <div className="divider" />
      <span className="section-label">🌐 Web reports for this route</span>
      {webBusy && webAdvisories.length === 0 && (
        <div className="hint">Researching recent road works, closures & warnings on the web…</div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {webAdvisories.map((a, i) => (
          <div className="agent-note" key={i} style={{ borderLeftColor: "#c9a227" }}>
            <div className="a-head" style={{ color: "#c9a227", display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ flex: 1 }}>{HAZARD_ICON[a.type] || "🌐"} {hazardLabel(a.type)} · {a.locality}</span>
              {a.date && (
                <span style={{ fontSize: 11, fontWeight: 600, whiteSpace: "nowrap", opacity: 0.9 }}>
                  📅 {fmtReportDate(a.date)}
                </span>
              )}
            </div>
            <div className="a-body">{a.summary}</div>
            <div className="hint" style={{ fontStyle: "italic" }}>
              source: {a.source}{a.date ? ` · reported ${fmtReportDate(a.date)}` : ""} · unverified, approximate
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

const VERDICT_META = {
  go: { color: "#33d08c", label: "Good to go", ic: "✓" },
  caution: { color: "#f0b429", label: "Go prepared", ic: "!" },
  wait: { color: "#ff6150", label: "Better to wait", ic: "⏸" },
};

function PrepPanel({ prep, plan, mode, proceed, webAdvisories, webBusy }) {
  const [items, setItems] = useState(() => prep.checklist.map((c) => ({ ...c })));
  const meta = VERDICT_META[prep.verdict] || VERDICT_META.caution;
  const firstLeg = plan?.first_leg;
  const packed = items.filter((i) => i.done).length;

  function toggle(idx) {
    setItems((list) => list.map((it, i) => (i === idx ? { ...it, done: !it.done } : it)));
  }

  return (
    <>
      <div className="verdict" style={{ borderColor: meta.color }}>
        <span className="v-badge" style={{ background: meta.color }}>{meta.ic}</span>
        <div>
          <div className="v-label" style={{ color: meta.color }}>{meta.label}</div>
          <div className="v-headline">{prep.headline}</div>
        </div>
      </div>

      <AgentNote agent={plan?.agent} />

      {firstLeg && (
        <div className="agent-note" style={{ borderLeftColor: "#f0b429" }}>
          <div className="a-head" style={{ color: "#f0b429" }}>🚶 First leg — walk to the station</div>
          <div className="a-body">
            {fmtKm(firstLeg.distance_m)} · {fmtMin(firstLeg.duration_s)} to{" "}
            <strong>{firstLeg.station?.name}</strong>.{" "}
            {firstLeg.hazards?.length > 0
              ? `${firstLeg.hazards.length} hazard(s) on the way — the most exposed part of your journey.`
              : "Looks clear on foot."}
          </div>
        </div>
      )}

      <div className="prep-head">
        <span className="section-label">Readiness checklist</span>
        <span className="prep-count">{packed}/{items.length} packed</span>
      </div>
      <div className="checklist">
        {items.map((c, i) => (
          <button key={i} className={`check-item ${c.done ? "done" : ""}`} onClick={() => toggle(i)}>
            <span className="box">{c.done ? "✓" : ""}</span>
            <span className="ci-text">
              <span className="ci-item">{c.item}</span>
              <span className="ci-reason">{c.reason}</span>
            </span>
          </button>
        ))}
      </div>

      <WebAdvisoriesBlock webAdvisories={webAdvisories} webBusy={webBusy} />

      <button className="btn btn-primary" onClick={proceed}>
        See safe routes →
      </button>
    </>
  );
}

function RoutesPanel({ plan, selectedRouteId, onSelect, selectedRoute, startGuardian, busy, webAdvisories, webBusy }) {
  return (
    <>
      <AgentNote agent={plan.agent} />
      <div className="hint">{plan.advice}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {plan.routes.map((r) => {
          const color = RATING_COLOR[r.rating] || "#25c7dc";
          const recommended = r.route_id === plan.recommended_route_id;
          return (
            <div
              key={r.route_id}
              className={`route-card ${r.route_id === selectedRouteId ? "selected" : ""}`}
              onClick={() => onSelect(r.route_id)}
            >
              <div className="route-top">
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="score-badge" style={{ color }}>◍ {r.score}</span>
                  {recommended && <span className="reco">recommended</span>}
                </div>
                <span className="rating" style={{ background: `${color}22`, color }}>{r.rating}</span>
              </div>
              <div className="route-meta">
                <span>{fmtKm(r.distance_m)}</span>
                <span>{fmtMin(r.duration_s)}</span>
                <span>{r.hazards.length} hazard{r.hazards.length === 1 ? "" : "s"}</span>
              </div>
              <div className="route-summary">{r.summary}</div>
            </div>
          );
        })}
      </div>

      {selectedRoute?.hazards?.length > 0 && (
        <>
          <div className="divider" />
          <span className="section-label">Hazards on this route</span>
          <div className="pills">
            {[...selectedRoute.hazards]
              .sort((a, b) => (a.distance_along_m ?? 0) - (b.distance_along_m ?? 0))
              .map((h, i) => (
                <span className="pill" key={i}>
                  {HAZARD_ICON[h.type] || "❗"} {hazardLabel(h.type)}
                  {h.distance_along_m != null && (
                    <span style={{ opacity: 0.6, marginLeft: 4 }}>· {fmtAhead(h.distance_along_m)}</span>
                  )}
                </span>
              ))}
          </div>
        </>
      )}

      {plan.precautions?.length > 0 && (
        <>
          <span className="section-label">Precautions</span>
          <ul className="precautions">
            {plan.precautions.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </>
      )}

      <WebAdvisoriesBlock webAdvisories={webAdvisories} webBusy={webBusy} />

      <button className="btn btn-primary" onClick={startGuardian} disabled={busy}>
        {busy ? "Starting…" : "Start Guardian on this route"}
      </button>
      <div className="hint">
        Once started, SafeJourney watches the road ahead on an adaptive interval and alerts
        you — even with the app closed (via push in the cloud build).
      </div>
    </>
  );
}

function GuardianChat({ trip }) {
  const [log, setLog] = useState([]); // {role:'user'|'agent', text, trace?}
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log, busy]);

  async function send() {
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    setLog((l) => [...l, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = await api.chat(q, trip?.id || "web", trip?.id || "");
      if (res.error) {
        setUnavailable(true);
        setLog((l) => [...l, { role: "agent", text: "Guardian AI isn't configured (no Gemini key) — the rule-based guardian is still watching your route.", trace: [] }]);
      } else {
        setLog((l) => [...l, { role: "agent", text: res.reply, trace: res.trace || [] }]);
      }
    } catch (e) {
      setLog((l) => [...l, { role: "agent", text: `Couldn't reach Guardian: ${e.message || e}`, trace: [] }]);
    } finally {
      setBusy(false);
    }
  }

  const suggestions = [
    "Is my route safe right now?",
    "Find me a safe place to wait",
    "What should I do if it floods ahead?",
  ];

  return (
    <div className="chat">
      <span className="section-label">Ask Guardian</span>
      {log.length === 0 && (
        <div className="pills">
          {suggestions.map((s) => (
            <button key={s} className="pill" style={{ cursor: "pointer" }} onClick={() => setText(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="chat-log">
        {log.map((m, i) => (
          <div className={`msg ${m.role}`} key={i}>
            <div className="bubble">{m.text}</div>
            {m.trace?.length > 0 && (
              <div className="trace">
                {m.trace.map((t, j) => (
                  <div className="step" key={j}>
                    {t.kind === "tool_call" ? (
                      <>
                        <span className="tk">🛠 call</span>
                        <span className="nm">{t.name}</span>
                      </>
                    ) : (
                      <>
                        <span className="tk">↳ result</span>
                        <span className="nm">{t.name}</span>
                        <span>· {t.summary}</span>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg agent"><div className="bubble">Guardian is thinking…</div></div>}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <input
          value={text}
          placeholder="Ask about your route…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn btn-primary" style={{ padding: "8px 14px" }} onClick={send} disabled={busy}>
          Send
        </button>
      </div>
    </div>
  );
}

function ActivePanel({ trip, alerts, safetyScore, injectHazard, advance, findHarbor, findMobility, findEssentials, essentials, reportHazard, mobility, gpsOn, toggleGps }) {
  const rating =
    safetyScore == null ? null : safetyScore <= 2 ? "safe" : safetyScore <= 6 ? "caution" : safetyScore <= 14 ? "risky" : "dangerous";
  const color = rating ? RATING_COLOR[rating] : "#7d9490";
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span className="beacon"><span /></span>
        <div>
          <div style={{ fontWeight: 600 }}>Guardian is watching</div>
          <div className="hint">Re-scanning the road ahead every few seconds.</div>
        </div>
        {safetyScore != null && (
          <div style={{ marginLeft: "auto", textAlign: "right" }}>
            <div className="section-label">road ahead</div>
            <div className="score-badge" style={{ color, fontSize: 16 }}>◍ {safetyScore} · {rating}</div>
          </div>
        )}
      </div>

      <div className="divider" />
      <div className="prep-head">
        <span className="section-label">Location</span>
        <button className={`gps-toggle ${gpsOn ? "on" : ""}`} onClick={toggleGps}>
          <span className="gps-dot" /> {gpsOn ? "Live GPS on" : "Use my location"}
        </button>
      </div>
      {gpsOn && <div className="hint">Streaming your real position — Guardian scans only the road ahead of you.</div>}

      <div className="divider" />
      <span className="section-label">See a hazard? Report it</span>
      <div className="hint">Files a geotagged report at your location so travellers behind you are warned.</div>
      <div className="pills">
        {REPORT_TYPES.map((rt) => (
          <button key={rt.type} className="pill report-pill" onClick={() => reportHazard(rt)}>
            {HAZARD_ICON[rt.type] || "❗"} {rt.label}
          </button>
        ))}
      </div>

      <div className="divider" />
      <span className="section-label">Simulate a hazard (demo)</span>
      <div className="pills">
        {DEMO_HAZARDS.map((h) => (
          <button key={h.type} className="pill" style={{ cursor: "pointer" }} onClick={() => injectHazard(h)}>
            {HAZARD_ICON[h.type]} {h.label}
          </button>
        ))}
      </div>

      <div className="btn-row">
        <button className="btn btn-ghost" onClick={() => advance(0.4)}>Advance ↦</button>
        <button className="btn btn-ghost" onClick={() => advance(0.8)}>Near end ↦</button>
        <button className="btn btn-ghost" onClick={() => findHarbor()}>Safe harbour</button>
        <button className="btn btn-ghost" onClick={() => findMobility()}>Alternatives</button>
        <button className="btn btn-ghost" onClick={() => findEssentials()}>Essentials</button>
      </div>

      {essentials?.length > 0 && (
        <div className="pills">
          {essentials.map((e, i) => (
            <span className="pill" key={i}>
              {e.icon || "🛒"} {e.label} · {fmtKm(e.distance_m)}
            </span>
          ))}
        </div>
      )}

      {mobility && (
        <>
          <div className="divider" />
          <span className="section-label">Safer ways to continue</span>
          <div className="mobility">
            {mobility.options?.map((o, i) => (
              <a className="mob-opt" key={i} href={o.url} target="_blank" rel="noreferrer">
                <span className="mob-ic">{o.kind === "cab" ? "🚕" : "🚇"}</span>
                <span className="mob-text">
                  <span className="mob-provider">{o.provider}</span>
                  <span className="mob-why">{o.why}</span>
                </span>
                <span className="mob-go">↗</span>
              </a>
            ))}
          </div>
          {mobility.nearest_station && (
            <div className="hint">
              Nearest station: <strong>{mobility.nearest_station.name}</strong> ·{" "}
              {fmtKm(mobility.nearest_station.distance_m)} away.
            </div>
          )}
        </>
      )}

      <div className="divider" />
      <GuardianChat trip={trip} />

      <div className="divider" />
      <span className="section-label">Alert feed</span>
      {alerts.length === 0 && <div className="hint">No alerts yet — the road ahead is clear.</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {alerts.map((a) => {
          const meta = ACTION_META[a.action] || { label: a.action, color: "#25c7dc" };
          return (
            <div className="alert" key={a.id} style={{ borderLeftColor: meta.color }}>
              <div className="a-top">
                <span className="a-action" style={{ color: meta.color }}>{meta.label}</span>
                <span className="a-time">{new Date(a.created_at * 1000).toLocaleTimeString()}</span>
              </div>
              <div className="a-title">{a.title}</div>
              <div className="a-msg">{a.message}</div>
              {(a.meta?.reason || a.meta?.decided_by) && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  {a.meta?.decided_by && (
                    <span className="decided-by">decided by {a.meta.decided_by}</span>
                  )}
                  {a.meta?.reason && (
                    <span className="hint" style={{ fontStyle: "italic" }}>{a.meta.reason}</span>
                  )}
                </div>
              )}
              {a.precautions?.length > 0 && (
                <ul className="precautions" style={{ marginTop: 4 }}>
                  {a.precautions.slice(0, 3).map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
