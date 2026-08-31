import { useEffect, useRef, useState } from "react";

/* ---- agent / tool display maps (powers the visible reasoning timeline) ---- */
export const AGENT_META = {
  guardian_core: { label: "Guardian Core", icon: "🧭", color: "#25c7dc" },
  guardian: { label: "Guardian Core", icon: "🧭", color: "#25c7dc" },
  prep: { label: "Prep Agent", icon: "🎒", color: "#9b8cff" },
  route_guardian: { label: "Route Guardian", icon: "🛡", color: "#33d08c" },
  safe_harbor: { label: "Safe Harbor", icon: "🏠", color: "#f0b429" },
  mobility: { label: "Mobility Agent", icon: "🚇", color: "#4aa8ff" },
  sos: { label: "SOS Guardian", icon: "🆘", color: "#ff6150" },
  hazard_sentinel: { label: "Hazard Sentinel", icon: "📡", color: "#f0b429" },
  decision_agent: { label: "Decision Agent", icon: "⚖", color: "#ff8a3d" },
};
export const agentMeta = (id) => AGENT_META[id] || { label: id || "Agent", icon: "◆", color: "#25c7dc" };

const TOOL_META = {
  plan_safe_routes: { icon: "🗺", label: "plan safe routes" },
  scan_route_hazards: { icon: "🔎", label: "scan road ahead" },
  check_trip_now: { icon: "📡", label: "read conditions" },
  get_safe_harbors: { icon: "🏠", label: "find safe harbours" },
  get_mobility_options: { icon: "🚇", label: "find alternatives" },
  get_precautions: { icon: "📋", label: "write the briefing" },
  report_incident: { icon: "⚠", label: "report incident" },
  change_detection: { icon: "🧮", label: "change detection" },
  find_reroute: { icon: "🧭", label: "search for safer path" },
  find_nearby: { icon: "📍", label: "find nearby" },
};
const ACTION_VERB = {
  reroute: "REROUTE",
  harbor: "TAKE SHELTER",
  advisory: "ADVISORY",
  sos: "ESCALATE / SOS",
  clear: "ALL CLEAR",
};
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

export function mergeCite(list, src) {
  if (!src) return list;
  const key = `${src.id || src.label}|${src.url || ""}`;
  if (list.some((s) => `${s.id || s.label}|${s.url || ""}` === key)) return list;
  return [...list, src];
}

const FLEET = ["guardian_core", "route_guardian", "hazard_sentinel", "prep"];

function activeAgent(trace) {
  if (!trace?.length) return "guardian_core";
  const last = [...trace].reverse().find((t) => t.kind === "delegate" || t.agent);
  if (last?.kind === "delegate") return last.to;
  return last?.agent || "guardian_core";
}

function doneAgents(trace) {
  const done = new Set();
  for (const t of trace || []) {
    if (t.kind === "delegate") done.add(t.from);
  }
  return done;
}

/* ---------- clickable source chips ---------- */
export function SourcesBar({ sources, label = "Sources" }) {
  const list = (sources || []).filter(Boolean);
  if (!list.length) return null;
  return (
    <div className="cite-bar">
      <span className="cite-kicker">{label}</span>
      <div className="cite-row">
        {list.map((s, i) => {
          const inner = (
            <>
              <span className="cite-ic">{s.icon || "📄"}</span>
              <span className="cite-name">{s.label || s.id || "Source"}</span>
              {s.url ? <span className="cite-ext">↗</span> : null}
            </>
          );
          const cls = `cite-chip ${s.url ? "linked" : ""}`;
          const title = s.blurb || s.label || "";
          return s.url ? (
            <a
              className={cls}
              key={`${s.id}-${i}`}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              title={title}
            >
              {inner}
            </a>
          ) : (
            <span className={cls} key={`${s.id}-${i}`} title={title}>
              {inner}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- the ordered tool/delegation timeline ---------- */
export function ReasoningTrace({ trace, sources, live = false, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  const scroller = useRef(null);
  const steps = (trace || []).filter((t) => t.kind !== "tool_result" || t.summary);
  const nCalls = (trace || []).filter((t) => t.kind === "tool_call").length;
  const nAgents = new Set(
    (trace || []).filter((t) => t.kind === "delegate").map((t) => t.to)
  ).size;
  const summary =
    `${nCalls} tool ${nCalls === 1 ? "call" : "calls"}` +
    (nAgents ? ` · ${nAgents} specialist${nAgents === 1 ? "" : "s"}` : "");

  useEffect(() => {
    if (!live || !open) return;
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [trace, live, open]);

  if (!steps.length && !live) return null;

  return (
    <div className={`reasoning ${open ? "open" : ""} ${live ? "live" : ""}`}>
      <button className="reason-head" onClick={() => setOpen((v) => !v)}>
        <span className="rh-pulse" aria-hidden />
        <span className="rh-title">{live ? "Live reasoning" : "Guardian reasoning"}</span>
        <span className="rh-sub">{live && !steps.length ? "waking the fleet…" : summary}</span>
        <span className="rh-chev">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <>
          <ol className="reason-steps" ref={scroller}>
            {steps.map((t, j) => {
              if (t.kind === "cite") return null;
              if (t.kind === "delegate") {
                const to = agentMeta(t.to);
                return (
                  <li className="rstep delegate" key={j}>
                    <span className="rdot" />
                    <span className="rbody">
                      <span className="deleg">
                        <span className="ag-badge">{agentMeta(t.from).icon} {agentMeta(t.from).label}</span>
                        <span className="arrow">→</span>
                        <span className="ag-badge to" style={{ background: to.color, borderColor: to.color }}>
                          {to.icon} {to.label}
                        </span>
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
                      {t.title && <span className="dec-title">{t.title}</span>}
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
              return (
                <li className="rstep result" key={j}>
                  <span className="rdot" />
                  <span className="rbody">
                    <span className="rresult">↳ {t.summary}</span>
                  </span>
                </li>
              );
            })}
            {live && <li className="rstep live-tail" key="tail"><span className="rdot" /><span className="rbody"><span className="rresult">listening…</span></span></li>}
          </ol>
          <SourcesBar sources={sources} />
        </>
      )}
    </div>
  );
}

function AgentFleet({ trace, live }) {
  const current = activeAgent(trace);
  const done = doneAgents(trace);
  return (
    <div className="fleet" role="list">
      {FLEET.map((id, i) => {
        const m = agentMeta(id);
        const isOn = current === id;
        const isDone = done.has(id) && !isOn;
        return (
          <div className={`fleet-node ${isOn ? "on" : ""} ${isDone ? "done" : ""}`} key={id} role="listitem">
            {i > 0 && <span className="fleet-wire" aria-hidden />}
            <span className="fleet-orb" style={{ "--ag": m.color }}>
              <span className="fleet-ic">{m.icon}</span>
            </span>
            <span className="fleet-name">{m.label.replace(" Agent", "").replace(" Guardian", "")}</span>
          </div>
        );
      })}
      {live && <span className="fleet-live">live</span>}
    </div>
  );
}

/** Full-panel theater shown in the sidebar while routes are being found. */
export function ReasoningTheater({
  trace,
  sources,
  originLabel,
  destLabel,
  modeLabel,
}) {
  const current = agentMeta(activeAgent(trace));
  return (
    <div className="theater">
      <div className="theater-kicker">
        <span className="th-pulse" />
        Finding the safest route
      </div>
      <div className="theater-path">
        <span className="th-end">{originLabel || "Start"}</span>
        <span className="th-arrow">→</span>
        <span className="th-end">{destLabel || "Destination"}</span>
      </div>
      {modeLabel && <div className="theater-mode">{modeLabel}</div>}
      <AgentFleet trace={trace} live />
      <div className="theater-now">
        <span className="th-now-ic">{current.icon}</span>
        <div>
          <div className="th-now-ag">{current.label}</div>
          <div className="th-now-line">{nowLine(trace)}</div>
        </div>
      </div>
      <ReasoningTrace trace={trace} sources={sources} live defaultOpen />
    </div>
  );
}

function nowLine(trace) {
  if (!trace?.length) return "Waking the specialist fleet…";
  const last = trace[trace.length - 1];
  if (last.kind === "delegate") return `Handing off to ${agentMeta(last.to).label}…`;
  if (last.kind === "tool_call") return `${toolMeta(last.name).label}…`;
  if (last.kind === "tool_result") return last.summary || "Reading the result…";
  if (last.kind === "decision") return last.reason || last.title || "Choosing the safest path…";
  if (last.kind === "cite") return `Grounded by ${last.source?.label || "a live feed"}`;
  return "Reasoning…";
}

/** Compact glass HUD over the map during a live scan. */
export function ScanHud({ trace, sources, visible }) {
  if (!visible) return null;
  const current = agentMeta(activeAgent(trace));
  const nCite = (sources || []).length;
  return (
    <div className="scan-hud" role="status" aria-live="polite">
      <div className="scan-hud-top">
        <span className="th-pulse" />
        <span className="scan-hud-kicker">Multi-agent scan</span>
      </div>
      <div className="scan-hud-now">
        <span className="scan-hud-ic">{current.icon}</span>
        <div>
          <div className="scan-hud-ag">{current.label}</div>
          <div className="scan-hud-line">{nowLine(trace)}</div>
        </div>
      </div>
      <AgentFleet trace={trace} live />
      {nCite > 0 && (
        <div className="scan-hud-cites">
          {(sources || []).slice(0, 5).map((s, i) =>
            s.url ? (
              <a
                className="cite-chip linked sm"
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
              >
                <span className="cite-ic">{s.icon || "📄"}</span>
                <span className="cite-name">{s.label}</span>
                <span className="cite-ext">↗</span>
              </a>
            ) : (
              <span className="cite-chip sm" key={i}>
                <span className="cite-ic">{s.icon || "📄"}</span>
                <span className="cite-name">{s.label}</span>
              </span>
            )
          )}
        </div>
      )}
    </div>
  );
}

/** Post-scan card: Gemini summary + full trace + clickable citations. */
export function PlanReasoningCard({ agent, traceOpen = true }) {
  if (!agent) return null;
  const sources = agent.sources || [];
  const trace = agent.trace || [];
  return (
    <div className="plan-reason">
      {agent.summary && (
        <div className="agent-note">
          <div className="a-head">
            <span className="beacon" style={{ transform: "scale(0.7)" }}><span /></span>
            Why this route
          </div>
          <div className="a-body">{agent.summary}</div>
        </div>
      )}
      {trace.length > 0 && <ReasoningTrace trace={trace} sources={sources} defaultOpen={traceOpen} />}
      {trace.length === 0 && sources.length > 0 && <SourcesBar sources={sources} label="grounded by" />}
    </div>
  );
}

/** Staged events used if the SSE stream isn't available — keeps the theater alive. */
export const FALLBACK_SCAN = [
  { kind: "delegate", from: "guardian_core", to: "route_guardian" },
  { kind: "tool_call", name: "plan_safe_routes", agent: "route_guardian", args: { mode: "live" } },
  { kind: "tool_result", name: "plan_safe_routes", agent: "route_guardian",
    summary: "Asking Directions for candidate corridors…" },
  { kind: "cite", source: { id: "google-directions", label: "Google Directions", icon: "🧭",
    url: "https://www.google.com/maps", blurb: "Candidate driving / walking paths" } },
  { kind: "delegate", from: "route_guardian", to: "hazard_sentinel" },
  { kind: "tool_call", name: "scan_route_hazards", agent: "hazard_sentinel",
    args: { feeds: "weather · OSM · disasters · blackspots" } },
  { kind: "cite", source: { id: "open-meteo", label: "Open-Meteo", icon: "🌤",
    url: "https://open-meteo.com", blurb: "Live weather, visibility & air quality" } },
  { kind: "cite", source: { id: "overpass", label: "OpenStreetMap", icon: "🗺",
    url: "https://www.openstreetmap.org", blurb: "Road works, lighting, crossings" } },
  { kind: "cite", source: { id: "gdacs", label: "GDACS", icon: "🚨",
    url: "https://www.gdacs.org", blurb: "Global disaster alerts" } },
  { kind: "tool_result", name: "scan_route_hazards", agent: "hazard_sentinel",
    summary: "Feeds returning — scoring each corridor on safety…" },
];

export function playFallbackScan(onEvent, { interval = 420 } = {}) {
  let i = 0;
  let stopped = false;
  const tick = () => {
    if (stopped) return;
    if (i >= FALLBACK_SCAN.length) return;
    onEvent(FALLBACK_SCAN[i]);
    i += 1;
    if (i < FALLBACK_SCAN.length) timer = setTimeout(tick, interval);
  };
  let timer = setTimeout(tick, 80);
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
