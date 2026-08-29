import { useEffect, useRef, useState, useCallback } from "react";
import MapView from "./components/MapView.jsx";
import { api } from "./api.js";
import { enablePush, fcmConfigured } from "./lib/fcm.js";
import { decodePolyline } from "./lib/polyline.js";
import { speak, speakNav, primeSpeech, cancelSpeech, speechSupported } from "./lib/speech.js";
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

// ---- agent-reasoning display maps (powers the visible reasoning timeline) ----
const AGENT_META = {
  guardian_core: { label: "Guardian Core", icon: "🧭" },
  guardian: { label: "Guardian Core", icon: "🧭" },
  prep: { label: "Prep Agent", icon: "🎒" },
  route_guardian: { label: "Route Guardian", icon: "🛡" },
  safe_harbor: { label: "Safe Harbor", icon: "🏠" },
  mobility: { label: "Mobility Agent", icon: "🚇" },
  sos: { label: "SOS Guardian", icon: "🆘" },
  hazard_sentinel: { label: "Hazard Sentinel", icon: "📡" },
  decision_agent: { label: "Decision Agent", icon: "⚖" },
};
const agentMeta = (id) => AGENT_META[id] || { label: id || "Agent", icon: "◆" };
const TOOL_META = {
  plan_safe_routes: { icon: "🗺", label: "plan safe routes" },
  scan_route_hazards: { icon: "🔎", label: "scan road ahead" },
  check_trip_now: { icon: "📡", label: "check trip now" },
  get_safe_harbors: { icon: "🏠", label: "find safe harbours" },
  get_mobility_options: { icon: "🚇", label: "find alternatives" },
  get_precautions: { icon: "📋", label: "get precautions" },
  report_incident: { icon: "⚠", label: "report incident" },
  change_detection: { icon: "🧮", label: "change detection" },
  find_reroute: { icon: "🧭", label: "search for safer path" },
};
const ACTION_VERB = {
  reroute: "REROUTE",
  harbor: "TAKE SHELTER",
  advisory: "ADVISORY",
  sos: "ESCALATE / SOS",
  clear: "ALL CLEAR",
};
const SEVERITY_RANK = { critical: 4, high: 3, moderate: 2, low: 1 };

// Fastest-route (what a plain nav app picks) vs. SafeJourney's safety-ranked pick.
// Everything is already on plan.routes, so this is a pure client-side derivation.
function routeComparison(plan) {
  const routes = plan?.routes || [];
  if (routes.length < 2) return null;
  const safest = routes.find((r) => r.route_id === plan.recommended_route_id) || routes[0];
  const fastest = routes.reduce((a, b) => {
    const da = a.duration_s || Infinity, db = b.duration_s || Infinity;
    if (da !== db) return da < db ? a : b;
    return (a.distance_m || Infinity) <= (b.distance_m || Infinity) ? a : b;
  });
  if (fastest.route_id === safest.route_id) return { agree: true, route: safest };
  // Hazards the fastest route hits that the safe route avoids (diff by type), worst first.
  const safeTypes = new Set((safest.hazards || []).map((h) => h.type));
  const avoided = (fastest.hazards || [])
    .filter((h) => !safeTypes.has(h.type))
    .sort((a, b) => (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0));
  const extraMin = Math.round(((safest.duration_s || 0) - (fastest.duration_s || 0)) / 60);
  return { agree: false, fastest, safest, avoided, extraMin };
}
const toolMeta = (name) => TOOL_META[name] || { icon: "🛠", label: name };
function fmtArgs(args) {
  if (!args || typeof args !== "object") return "";
  const parts = [];
  for (const [k, v] of Object.entries(args)) {
    if (v == null || v === "") continue;
    let s = typeof v === "object" ? JSON.stringify(v) : String(v);
    if (s.length > 28) s = s.slice(0, 27) + "…";
    parts.push(`${k}: ${s}`);
    if (parts.length >= 3) break;
  }
  return parts.join(" · ");
}
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
// Phrase a route step as a spoken turn-by-turn line, optionally with a lead-in distance.
function navLine(instruction, meters) {
  let instr = (instruction || "Continue ahead").trim();
  // Trim Google's verbose landmark tails so the spoken line stays short and clear.
  instr = instr.split(/\s+Pass by\s+/i)[0];        // "…onto MG Rd Pass by the shop" → "…onto MG Rd"
  instr = instr.replace(/\s*\([^)]*\)/g, "").trim(); // drop "(on the right)" style hints
  if (!instr) instr = "Continue ahead";
  if (!meters) return instr;
  const rounded = meters >= 1000 ? `${(meters / 1000).toFixed(1)} kilometers` : `${Math.round(meters / 10) * 10} meters`;
  return `In ${rounded}, ${instr.charAt(0).toLowerCase()}${instr.slice(1)}`;
}
function fmtStepDist(m) {
  if (!m) return "";
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
  const [pedFeatures, setPedFeatures] = useState([]);
  const [webAdvisories, setWebAdvisories] = useState([]);
  const [webBusy, setWebBusy] = useState(false);
  const [mobility, setMobility] = useState(null);
  const [position, setPosition] = useState(null);
  const [simulating, setSimulating] = useState(false);
  const simRef = useRef(null);
  const [safetyScore, setSafetyScore] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [voiceOn, setVoiceOn] = useState(() => {
    try { return localStorage.getItem("sj_voice") !== "off"; } catch { return true; }
  });
  const [status, setStatus] = useState({ online: null, msg: "Checking backend…" });
  const [busy, setBusy] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  const [focusPoint, setFocusPoint] = useState(null);
  const seenAlerts = useRef(new Set());
  const warnedProx = useRef(new Set());
  const navIdx = useRef(0);          // next route step to narrate
  const navPre = useRef(new Set());  // step indices already pre-announced ("in 200 m…")
  const spokenProx = useRef(new Set()); // hazards whose proximity warning was actually voiced
  const arrivedSpoken = useRef(false);

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

  // Walk mode: fetch pedestrian infrastructure (foot-over-bridges, crossings, underpasses)
  // for the selected route so the map can mark where to cross safely.
  const selectedPolyline = selectedRoute?.encoded_polyline;
  useEffect(() => {
    if (phase !== "routes" || mode !== "walk" || !selectedPolyline) {
      setPedFeatures([]);
      return;
    }
    let cancelled = false;
    api
      .pedestrianRoute(selectedPolyline)
      .then((r) => { if (!cancelled) setPedFeatures(r.features || []); })
      .catch(() => { if (!cancelled) setPedFeatures([]); });
    return () => { cancelled = true; };
  }, [phase, mode, selectedPolyline]);

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
    // This click is a user gesture — unlock audio and greet, so later alerts can speak.
    if (voiceOn) { primeSpeech(); speak("Guardian is now watching your route. I'll warn you before any hazard."); }
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
      navIdx.current = 0;
      navPre.current = new Set();
      arrivedSpoken.current = false;
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

  // stop the simulated drive if the view unmounts
  useEffect(() => () => { if (simRef.current) cancelAnimationFrame(simRef.current); }, []);

  // active monitoring loop (client drives ticks locally; in cloud, Scheduler does this)
  useEffect(() => {
    if (phase !== "active" || !trip) return;
    let alive = true;
    const loop = async () => {
      try {
        await api.evaluate(trip.id);
        if (alive) await refresh(trip.id);
      } catch {}
    };
    const iv = setInterval(loop, 6000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [phase, trip]);

  // Proximity alert: warn ~350 m BEFORE the traveller reaches a known hazard, so the notice
  // lands ahead of the point, not after crossing it. Checked on every position update (each
  // animation frame during the simulated drive), so no hazard is skipped.
  useEffect(() => {
    if (phase !== "active" || !position || !hazards.length) return;
    for (const h of hazards) {
      const key = `${h.type}:${h.lat.toFixed(4)}:${h.lng.toFixed(4)}`;
      const d = haversineM(position.lat, position.lng, h.lat, h.lng);
      if (d <= 350 && !warnedProx.current.has(key)) {
        warnedProx.current.add(key);
        pushToast(
          `${HAZARD_ICON[h.type] || "❗"} ${hazardLabel(h.type)} · ${Math.round(d)} m ahead`,
          h.description || "Approaching a hazard — slow down and stay alert.",
          "#ff8a3d"
        );
      }
      // Voice the warning independently of the toast, and retry until it actually speaks
      // (speakNav yields when something else is talking) — so it isn't lost mid-sim.
      if (voiceOn && d <= 350 && !spokenProx.current.has(key)) {
        if (speakNav(`Caution, ${hazardLabel(h.type).toLowerCase()} about ${Math.round(d / 10) * 10} meters ahead. Slow down.`)) {
          spokenProx.current.add(key);
        }
      } else if (d > 550) {
        warnedProx.current.delete(key); // re-arm once well past, so a loop back re-warns
        spokenProx.current.delete(key);
      }
    }
  }, [position, hazards, phase]);

  // Turn-by-turn voice guidance: as the traveller approaches each route step, narrate the
  // maneuver ("in 200 meters, turn left onto MG Road") like a nav app. Lower priority than a
  // safety alert (speakNav yields to it). Uses the selected route's steps.
  useEffect(() => {
    if (phase !== "active" || !voiceOn || !position) return;
    const steps = selectedRoute?.meta?.steps || [];
    if (!steps.length) return;
    let i = navIdx.current;
    while (i < steps.length) {
      const s = steps[i];
      if (!s?.start || s.start.lat == null) { i++; continue; }
      const d = haversineM(position.lat, position.lng, s.start.lat, s.start.lng);
      if (d < 35) {
        if (navPre.current.has(i)) { i++; continue; } // already announced — move on
        // At the maneuver and not yet announced: speak it plainly. If speakNav yields (channel
        // busy with a greeting/alert), DON'T advance — retry next tick so the turn isn't lost.
        if (speakNav(navLine(s.instruction, 0))) { navPre.current.add(i); i++; continue; }
        break;
      }
      if (d < 220 && !navPre.current.has(i)) {
        // Only mark announced if it actually spoke; otherwise retry on the next position tick.
        if (speakNav(navLine(s.instruction, d))) navPre.current.add(i);
        break;
      }
      // Step is far (>220 m). If we've clearly passed it — the NEXT step's start is now closer
      // — skip ahead so navigation keeps progressing (a turn missed while the channel was busy
      // never freezes the guidance). Otherwise it's still ahead: wait.
      const nxt = steps[i + 1];
      if (nxt?.start && nxt.start.lat != null &&
          haversineM(position.lat, position.lng, nxt.start.lat, nxt.start.lng) < d) {
        i++;
        continue;
      }
      break; // still upcoming but far — wait
    }
    navIdx.current = i;

    // Near the destination — announce arrival once.
    if (!arrivedSpoken.current) {
      const dest = trip?.destination;
      if (dest && haversineM(position.lat, position.lng, dest.lat, dest.lng) < 60) {
        arrivedSpoken.current = true;
        speakNav("You have arrived at your destination. Stay safe.");
      }
    }
  }, [position, phase, voiceOn, selectedRoute, trip]);

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

  function toggleVoice() {
    setVoiceOn((v) => {
      const next = !v;
      try { localStorage.setItem("sj_voice", next ? "on" : "off"); } catch {}
      if (!next) cancelSpeech();
      else primeSpeech(); // this toggle is a user gesture — unlock audio
      return next;
    });
  }

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
            // Speak the alert aloud — the hands-free safety moment.
            if (voiceOn) speak(`${a.title}. ${a.message}`);
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
      await api.evaluate(trip.id);
      await refresh(trip.id);
    } catch (e) {
      pushToast("Demo failed", String(e.message || e), "#ff6150");
    }
  }

  async function resetDemo() {
    try {
      const res = await api.resetDemo();
      seenAlerts.current = new Set(); // let a re-injected hazard alert again
      pushToast("Demo reset", `Cleared ${res.cleared_incidents || 0} test hazard(s) — clean slate for a fresh run.`, "#33d08c");
      if (trip) await refresh(trip.id, true);
    } catch (e) {
      pushToast("Reset failed", String(e.message || e), "#ff6150");
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

  // Judge demo: glide a traveller along the route at a realistic pace (~1 km per minute),
  // streaming its position so the live guardian flow (road-ahead scans, proximity warnings,
  // arrival) plays out on its own — no real travel needed.
  function stopSim() {
    if (simRef.current) cancelAnimationFrame(simRef.current);
    simRef.current = null;
    setSimulating(false);
  }
  function simulateJourney() {
    if (!trip?.encoded_polyline) return;
    if (simulating) { stopSim(); return; }
    const coords = decodePolyline(trip.encoded_polyline); // [lng, lat]
    if (coords.length < 2) return;
    // cumulative distance along the line so speed is even regardless of vertex spacing
    const cum = [0];
    for (let i = 1; i < coords.length; i++) {
      cum.push(cum[i - 1] + haversineM(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0]));
    }
    const total = cum[cum.length - 1] || 1;
    // Realistic pace: ~1 km per minute (~60 km/h), clamped so a tiny route still lasts long
    // enough to see and a long one doesn't drag. This keeps hazard warnings well-timed.
    const durationMs = Math.min(150000, Math.max(20000, (total / 1000) * 60000));
    setSimulating(true);
    setGpsOn(false);              // simulated position overrides any live GPS
    warnedProx.current = new Set(); // re-arm proximity warnings for the run
    navIdx.current = 0;             // restart turn-by-turn guidance from the first step
    navPre.current = new Set();
    arrivedSpoken.current = false;
    if (voiceOn) speak("Starting navigation. I'll guide you turn by turn and warn you of hazards ahead.");
    const start = performance.now();
    let lastPush = 0;
    const step = (now) => {
      const t = Math.min(1, (now - start) / durationMs);
      const d = t * total;
      let i = 1;
      while (i < cum.length && cum[i] < d) i++;
      const p0 = coords[i - 1], p1 = coords[Math.min(i, coords.length - 1)];
      const seg = (cum[Math.min(i, cum.length - 1)] - cum[i - 1]) || 1;
      const fr = Math.max(0, Math.min(1, (d - cum[i - 1]) / seg));
      const pos = { lat: p0[1] + (p1[1] - p0[1]) * fr, lng: p0[0] + (p1[0] - p0[0]) * fr };
      setPosition(pos);
      if (now - lastPush > 1500) { // stream to the backend a few times, not every frame
        lastPush = now;
        api.setPosition(trip.id, pos.lat, pos.lng).catch(() => {});
      }
      if (t < 1) {
        simRef.current = requestAnimationFrame(step);
      } else {
        simRef.current = null;
        setSimulating(false);
        api.setPosition(trip.id, pos.lat, pos.lng).catch(() => {});
        pushToast("Arrived", "Simulated journey complete — you reached the destination.", "#33d08c");
      }
    };
    simRef.current = requestAnimationFrame(step);
  }

  async function findHarbor(point, silent = false) {
    try {
      let harbors = [];
      if (trip?.encoded_polyline) {
        // Cover the WHOLE path so a refuge is reachable from anywhere, not just start/end.
        harbors = (await api.safeHarborsRoute(trip.encoded_polyline)).harbors || [];
      } else {
        const p = point || position;
        if (!p) return;
        harbors = (await api.safeHarbors(p.lat, p.lng)).harbors || [];
      }
      setHarbors(harbors);
      if (!silent) pushToast("Safe harbours on your route", `${harbors.length} refuge(s) marked along the whole path.`, "#f0b429");
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
      if (trip) { await api.evaluate(trip.id); await refresh(trip.id); }
    } catch (e) {
      pushToast("Report failed", String(e.message || e), "#ff6150");
    }
  }

  async function reportHazardText(text) {
    const p = position;
    if (!p) {
      pushToast("No location yet", "Turn on GPS or advance so I know where the hazard is.", "#f0b429");
      return null;
    }
    const q = (text || "").trim();
    if (!q) return null;
    try {
      const res = await api.triageReport(q, p.lat, p.lng);
      const t = res.triage || {};
      const via = t.source === "gemma" ? "Gemma" : "keyword match";
      if (res.incident) {
        const color = ["critical", "high"].includes(t.severity) ? "#ff6150" : t.severity === "moderate" ? "#f0b429" : "#33d08c";
        pushToast(`Classified: ${hazardLabel(t.type)} · ${t.severity}`, `${via} understood your report and filed it — travellers behind you are warned.`, color);
      } else {
        pushToast("Couldn't classify that", "No clear road hazard found — try naming it (flood, live wire, pothole, accident…).", "#f0b429");
      }
      if (trip) { await api.evaluate(trip.id); await refresh(trip.id); }
      return res;
    } catch (e) {
      pushToast("Report failed", String(e.message || e), "#ff6150");
      return null;
    }
  }

  async function findEssentials(point, silent = false) {
    try {
      let essentials = [];
      if (trip?.encoded_polyline) {
        // Pharmacies / fuel / ATMs / stores along the ENTIRE route, not just the ends.
        essentials = (await api.essentialsRoute(trip.encoded_polyline)).essentials || [];
      } else {
        const p = point || position || origin;
        if (!p) return;
        essentials = (await api.essentials(p.lat, p.lng)).essentials || [];
      }
      setEssentials(essentials);
      if (!silent) pushToast("Essentials on your route", `${essentials.length} place(s) marked along the whole path.`, "#8ad6ff");
    } catch {}
  }

  async function arrived() {
    stopSim();
    cancelSpeech();
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
    setPedFeatures([]);
    setWebAdvisories([]);
    setMobility(null);
    setPosition(null);
    setSafetyScore(null);
  }

  function pushToast(title, msg, color) {
    const id = Math.random().toString(36).slice(2);
    // Keep at most 2 on screen — a new toast drops the oldest so they don't stack up.
    setToasts((t) => [...t, { id, title, msg, color }].slice(-2));
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
          {speechSupported() && (
            <button
              className={`btn btn-ghost voice-toggle ${voiceOn ? "on" : ""}`}
              style={{ padding: "8px 11px" }}
              onClick={toggleVoice}
              title={voiceOn ? "Spoken alerts on" : "Spoken alerts off"}
              aria-label="Toggle spoken alerts"
            >
              {voiceOn ? "🔊" : "🔇"}
            </button>
          )}
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
              resetDemo={resetDemo}
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
              mode={mode}
              pedFeatures={pedFeatures}
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
              reportHazardText={reportHazardText}
              resetDemo={resetDemo}
              mobility={mobility}
              gpsOn={gpsOn}
              toggleGps={() => setGpsOn((v) => !v)}
              simulateJourney={simulateJourney}
              simulating={simulating}
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
        pedFeatures={phase === "routes" && mode === "walk" ? pedFeatures : []}
        webAdvisories={phase === "prep" || phase === "routes" || phase === "active" ? webAdvisories : []}
        origin={phase !== "active" ? origin : trip?.origin}
        destination={phase !== "active" ? destination : trip?.destination}
        position={phase === "active" ? position : null}
        travelerMode={trip?.mode}
        followTraveler={simulating}
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

function PlanPanel({ mode, setMode, presetIdx, applyPreset, setting, setSetting, origin, destination, originLabel, destLabel, pickOrigin, pickDestination, findRoute, resetDemo, busy, online }) {
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
      <button className="btn btn-ghost" style={{ marginTop: 8, fontSize: 12 }} onClick={resetDemo} disabled={online === false} title="Clear leftover test hazards from previous runs">
        ↺ Reset demo data
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

function RouteTradeoff({ plan, onSelect }) {
  const cmp = routeComparison(plan);
  if (!cmp) return null;

  if (cmp.agree) {
    return (
      <div className="tradeoff agree">
        <span className="to-agree-title">✓ The fastest route is also the safest</span>
        <span className="to-agree-sub">
          SafeJourney checked every alternative — no trade-off needed this time.
        </span>
      </div>
    );
  }

  const { fastest, safest, avoided, extraMin } = cmp;
  const worst = avoided[0];
  const timeTag = extraMin > 0 ? `+${extraMin} min` : extraMin < 0 ? `${extraMin} min` : "same time";
  const costPhrase = extraMin > 0 ? `${extraMin} min more` : extraMin < 0 ? `${-extraMin} min less` : "no extra time";
  const Col = ({ kind, label, r, tag }) => {
    const color = RATING_COLOR[r.rating] || "#25c7dc";
    return (
      <button className={`to-col ${kind}`} onClick={() => onSelect?.(r.route_id)} title="Show this route on the map">
        <span className="to-col-label">{label}</span>
        <span className="to-time">
          {fmtMin(r.duration_s)}
          {tag && <em className="to-tag">{tag}</em>}
        </span>
        <span className="to-rate" style={{ color }}>◍ {r.score} · {r.rating}</span>
        <span className="to-haz">{r.hazards.length} hazard{r.hazards.length === 1 ? "" : "s"} on path</span>
      </button>
    );
  };

  return (
    <div className="tradeoff">
      <div className="to-head">Why not just the fastest route?</div>
      <div className="to-grid">
        <Col kind="fast" label="🕐 Fastest (typical nav)" r={fastest} />
        <span className="to-vs">vs</span>
        <Col kind="safe" label="🛡 SafeJourney pick" r={safest} tag={timeTag} />
      </div>
      <div className="to-verdict">
        {worst ? (
          <>
            For <strong>{costPhrase}</strong>, SafeJourney routes you around a{" "}
            <strong className="to-hz">{HAZARD_ICON[worst.type] || "❗"} {worst.severity} {hazardLabel(worst.type)}</strong>{" "}
            that the fastest route runs straight through
            {worst.description ? ` — ${worst.description.replace(/[.\s]+$/, "")}` : ""}.
          </>
        ) : (
          <>
            The fastest route is rated <strong className="to-hz">{fastest.rating}</strong> (score {fastest.score});
            SafeJourney's pick is <strong style={{ color: RATING_COLOR[safest.rating] }}>{safest.rating}</strong>{" "}
            (score {safest.score}) — safer for {costPhrase}.
          </>
        )}
      </div>
    </div>
  );
}

function RoutesPanel({ plan, selectedRouteId, onSelect, selectedRoute, startGuardian, busy, webAdvisories, webBusy, mode, pedFeatures = [] }) {
  const steps = selectedRoute?.meta?.steps || [];
  const isWalk = mode === "walk";
  return (
    <>
      <AgentNote agent={plan.agent} />
      <div className="hint">{plan.advice}</div>
      <RouteTradeoff plan={plan} onSelect={onSelect} />
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

      {isWalk && pedFeatures.length > 0 && (
        <>
          <div className="divider" />
          <span className="section-label">Safe crossings on foot ({pedFeatures.length})</span>
          <div className="hint" style={{ marginTop: -2 }}>
            Foot-over-bridges, crossings and underpasses — all marked on the map.
          </div>
          <div className="pills">
            {pedFeatures.slice(0, 12).map((f, i) => (
              <span className="pill" key={i} title={f.label}>
                {f.icon} {f.label}
              </span>
            ))}
            {pedFeatures.length > 12 && (
              <span className="pill" style={{ opacity: 0.7 }}>
                +{pedFeatures.length - 12} more
              </span>
            )}
          </div>
        </>
      )}

      {isWalk && steps.length > 0 && (
        <>
          <div className="divider" />
          <span className="section-label">Walking directions</span>
          <ol className="directions">
            {steps.map((s, i) => (
              <li key={i}>
                <span className="dir-text">
                  {s.icon ? `${s.icon} ` : ""}{s.instruction}
                </span>
                {s.distance_m > 0 && (
                  <span className="dir-dist">{fmtStepDist(s.distance_m)}</span>
                )}
              </li>
            ))}
          </ol>
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

function ReasoningTrace({ trace }) {
  const [open, setOpen] = useState(true);
  const steps = trace.filter((t) => t.kind !== "tool_result" || t.summary);
  const nCalls = trace.filter((t) => t.kind === "tool_call").length;
  const nAgents = new Set(
    trace.filter((t) => t.kind === "delegate").map((t) => t.to)
  ).size;
  const summary =
    `${nCalls} tool ${nCalls === 1 ? "call" : "calls"}` +
    (nAgents ? ` · ${nAgents} specialist${nAgents === 1 ? "" : "s"}` : "");

  return (
    <div className={`reasoning ${open ? "open" : ""}`}>
      <button className="reason-head" onClick={() => setOpen((v) => !v)}>
        <span className="rh-title">◆ Guardian reasoning</span>
        <span className="rh-sub">{summary}</span>
        <span className="rh-chev">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <ol className="reason-steps">
          {steps.map((t, j) => {
            if (t.kind === "delegate") {
              const to = agentMeta(t.to);
              return (
                <li className="rstep delegate" key={j}>
                  <span className="rdot" />
                  <span className="rbody">
                    <span className="deleg">
                      <span className="ag-badge">{agentMeta(t.from).icon} {agentMeta(t.from).label}</span>
                      <span className="arrow">→</span>
                      <span className="ag-badge to">{to.icon} {to.label}</span>
                    </span>
                    <span className="rmeta">delegated</span>
                  </span>
                </li>
              );
            }
            if (t.kind === "decision") {
              return (
                <li className="rstep decision" key={j}>
                  <span className="rdot" />
                  <span className="rbody">
                    <span className="rline">
                      <span className="ricon">⚖</span>
                      <span className="dec-verdict">{ACTION_VERB[t.action] || t.action}</span>
                      {t.decided_by && (
                        <span className="dec-by">decided by {t.decided_by}</span>
                      )}
                    </span>
                    {t.reason && <span className="dec-reason">{t.reason}</span>}
                  </span>
                </li>
              );
            }
            if (t.kind === "tool_call") {
              const tm = toolMeta(t.name);
              const args = fmtArgs(t.args);
              return (
                <li className="rstep call" key={j}>
                  <span className="rdot" />
                  <span className="rbody">
                    <span className="rline">
                      <span className="ricon">{tm.icon}</span>
                      <span className="rname">{tm.label}</span>
                      {t.agent && <span className="rby">{agentMeta(t.agent).label}</span>}
                    </span>
                    {args && <span className="rargs">{args}</span>}
                  </span>
                </li>
              );
            }
            // tool_result
            return (
              <li className="rstep result" key={j}>
                <span className="rdot" />
                <span className="rbody">
                  <span className="rresult">↳ {t.summary}</span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
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
            {m.trace?.length > 0 && <ReasoningTrace trace={m.trace} />}
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

function NaturalReport({ onReport }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // last triage {type,severity,source,confidence}
  const [listening, setListening] = useState(false);
  const recRef = useRef(null);

  const SR = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

  function toggleMic() {
    if (!SR) return;
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = "en-IN";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const tr = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += tr;
        else interim += tr;
      }
      setText((finalText + interim).trim());
    };
    rec.onend = () => { setListening(false); recRef.current = null; };
    rec.onerror = () => { setListening(false); recRef.current = null; };
    recRef.current = rec;
    setListening(true);
    rec.start();
  }

  async function submit() {
    const q = text.trim();
    if (!q || busy) return;
    recRef.current?.stop();
    setBusy(true);
    setResult(null);
    try {
      const res = await onReport?.(q);
      if (res?.triage) setResult(res.triage);
      if (res?.incident) setText("");
    } finally {
      setBusy(false);
    }
  }

  const sevColor = (s) => (["critical", "high"].includes(s) ? "var(--danger)" : s === "moderate" ? "var(--caution)" : "var(--safe)");

  return (
    <div className="nl-report">
      <div className="nl-row">
        <input
          className="nl-input"
          value={text}
          placeholder='Describe it — e.g. "live wire in the water under the bridge"'
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={busy}
        />
        {SR && (
          <button
            className={`nl-mic ${listening ? "on" : ""}`}
            onClick={toggleMic}
            title={listening ? "Stop" : "Speak your report"}
            aria-label="Voice report"
          >
            {listening ? "●" : "🎤"}
          </button>
        )}
        <button className="btn btn-primary nl-send" onClick={submit} disabled={busy || !text.trim()}>
          {busy ? "…" : "Report"}
        </button>
      </div>
      <div className="nl-caption">
        {busy ? (
          <span className="nl-analyzing">🧠 Gemma is classifying your report…</span>
        ) : listening ? (
          <span className="nl-listening">● Listening…</span>
        ) : result ? (
          <span className="nl-result">
            <span className="nl-via">{result.source === "gemma" ? "🧠 Gemma" : "⌨ keyword"}</span>
            {" → "}
            <span style={{ color: sevColor(result.severity), fontWeight: 600 }}>
              {HAZARD_ICON[result.type] || "❗"} {hazardLabel(result.type)} · {result.severity}
            </span>
            {result.source === "gemma" && result.confidence != null && (
              <span className="nl-conf"> ({Math.round(result.confidence * 100)}% conf.)</span>
            )}
          </span>
        ) : (
          <span className="hint" style={{ margin: 0 }}>Type or speak naturally — a model files it under the right hazard.</span>
        )}
      </div>
    </div>
  );
}

function ActivePanel({ trip, alerts, safetyScore, injectHazard, advance, findHarbor, findMobility, findEssentials, essentials, reportHazard, reportHazardText, resetDemo, mobility, gpsOn, toggleGps, simulateJourney, simulating }) {
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

      <button
        className={`btn ${simulating ? "btn-ghost" : "btn-primary"}`}
        style={{ marginTop: 12 }}
        onClick={simulateJourney}
      >
        {simulating ? "⏹ Stop simulation" : `▶ Simulate the drive (${MODES.find((m) => m.id === trip?.mode)?.label || "travel"} · ~1 min)`}
      </button>
      <div className="hint">
        Watch a {MODES.find((m) => m.id === trip?.mode)?.label?.toLowerCase() || "traveller"} drive the whole
        route on the map while Guardian scans the road ahead and alerts on hazards — no real travel needed.
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
      <NaturalReport onReport={reportHazardText} />
      <div className="pills" style={{ marginTop: 8 }}>
        {REPORT_TYPES.map((rt) => (
          <button key={rt.type} className="pill report-pill" onClick={() => reportHazard(rt)}>
            {HAZARD_ICON[rt.type] || "❗"} {rt.label}
          </button>
        ))}
      </div>

      <div className="divider" />
      <div className="prep-head">
        <span className="section-label">Simulate a hazard (demo)</span>
        <button className="gps-toggle" onClick={resetDemo} title="Clear leftover test hazards">↺ Reset</button>
      </div>
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
              {a.meta?.trace?.length > 0 ? (
                <ReasoningTrace trace={a.meta.trace} />
              ) : (
                (a.meta?.reason || a.meta?.decided_by) && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {a.meta?.decided_by && (
                      <span className="decided-by">decided by {a.meta.decided_by}</span>
                    )}
                    {a.meta?.reason && (
                      <span className="hint" style={{ fontStyle: "italic" }}>{a.meta.reason}</span>
                    )}
                  </div>
                )
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
