import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { decodePolyline, bounds } from "../lib/polyline.js";
import { SEVERITY_COLOR, RATING_COLOR, HAZARD_ICON, hazardLabel } from "../lib/hazards.js";

const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0a1418" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 0.82, "raster-saturation": -0.3, "raster-brightness-min": 0.05 } },
  ],
};

function marker(color, glyph, size = 26) {
  const el = document.createElement("div");
  el.style.cssText = `width:${size}px;height:${size}px;border-radius:50%;background:${color};
    display:flex;align-items:center;justify-content:center;font-size:${size * 0.5}px;
    box-shadow:0 0 0 4px rgba(0,0,0,.25),0 2px 8px rgba(0,0,0,.5);border:2px solid #0a1418;color:#04252b;font-weight:700`;
  el.textContent = glyph;
  return el;
}

export default function MapView({
  mapMode,
  routes = [],
  selectedRouteId,
  activePolyline,
  hazards = [],
  harbors = [],
  origin,
  destination,
  position,
  onMapClick,
  fitKey,
  focusPoint,
}) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const clickCb = useRef(onMapClick);
  clickCb.current = onMapClick;

  // init once
  useEffect(() => {
    const styleUrl = import.meta.env.VITE_MAP_STYLE_URL;
    const map = new maplibregl.Map({
      container: ref.current,
      style: styleUrl || OSM_STYLE,
      center: [77.62, 12.972],
      zoom: 11,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addSource("routes", { type: "geojson", data: fc([]) });
      map.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#25c7dc"],
          "line-width": ["case", ["get", "selected"], 7, 4],
          "line-opacity": ["case", ["get", "selected"], 0.95, 0.5],
        },
      });
      map.addSource("hazards", { type: "geojson", data: fc([]) });
      map.addLayer({
        id: "hazards-halo",
        type: "circle",
        source: "hazards",
        paint: {
          "circle-radius": 16,
          "circle-color": ["get", "color"],
          "circle-opacity": 0.18,
        },
      });
      map.addLayer({
        id: "hazards-dot",
        type: "circle",
        source: "hazards",
        paint: {
          "circle-radius": 7,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#0a1418",
        },
      });
      map.on("click", "hazards-dot", (e) => {
        const p = e.features[0].properties;
        new maplibregl.Popup({ offset: 12 })
          .setLngLat(e.lngLat)
          .setHTML(`<b>${p.icon || "❗"} ${p.label}</b><br/>${p.desc || ""}`)
          .addTo(map);
      });
      map.on("mouseenter", "hazards-dot", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "hazards-dot", () => (map.getCanvas().style.cursor = ""));
      mapRef.current = map;
      // trigger first data render
      map._sjReady = true;
      map.fire("sjready");
    });
    map.on("click", (e) => {
      if (clickCb.current) clickCb.current({ lat: e.lngLat.lat, lng: e.lngLat.lng });
    });
    return () => map.remove();
  }, []);

  // update routes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource) return;
    const apply = () => {
      const feats = [];
      if (mapMode === "active" && activePolyline) {
        feats.push(lineFeature(decodePolyline(activePolyline), "#25c7dc", true));
      } else {
        for (const r of routes) {
          const coords = decodePolyline(r.encoded_polyline);
          const sel = r.route_id === selectedRouteId;
          feats.push(lineFeature(coords, RATING_COLOR[r.rating] || "#25c7dc", sel));
        }
      }
      const src = map.getSource("routes");
      if (src) src.setData(fc(feats));
    };
    if (map._sjReady) apply();
    else map.once("sjready", apply);
  }, [routes, selectedRouteId, activePolyline, mapMode]);

  // update hazards
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource) return;
    const apply = () => {
      const feats = hazards.map((h) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [h.lng, h.lat] },
        properties: {
          color: SEVERITY_COLOR[h.severity] || "#f0b429",
          label: `${hazardLabel(h.type)} (${h.severity})`,
          desc: h.description || "",
          icon: HAZARD_ICON[h.type] || "❗",
        },
      }));
      const src = map.getSource("hazards");
      if (src) src.setData(fc(feats));
    };
    if (map._sjReady) apply();
    else map.once("sjready", apply);
  }, [hazards]);

  // markers (origin/dest/position/harbors)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    const add = (lngLat, el) => {
      const m = new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(map);
      markersRef.current.push(m);
    };
    if (origin) add([origin.lng, origin.lat], marker("#33d08c", "A"));
    if (destination) add([destination.lng, destination.lat], marker("#25c7dc", "B"));
    if (position) add([position.lng, position.lat], marker("#ffffff", "●", 20));
    harbors.forEach((h) => add([h.lng, h.lat], marker("#f0b429", "🏠", 24)));
  }, [origin, destination, position, harbors]);

  // fly to a just-picked location (search result / GPS) for a responsive "search" feel
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusPoint) return;
    const apply = () =>
      map.flyTo({ center: [focusPoint.lng, focusPoint.lat], zoom: 15, duration: 900, essential: true });
    if (map._sjReady) apply();
    else map.once("sjready", apply);
  }, [focusPoint]);

  // fit bounds
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      let coords = [];
      if (mapMode === "active" && activePolyline) coords = decodePolyline(activePolyline);
      else routes.forEach((r) => (coords = coords.concat(decodePolyline(r.encoded_polyline))));
      if (origin) coords.push([origin.lng, origin.lat]);
      if (destination) coords.push([destination.lng, destination.lat]);
      if (coords.length >= 2) {
        map.fitBounds(bounds(coords), { padding: 70, duration: 700, maxZoom: 15 });
      } else if (coords.length === 1) {
        map.easeTo({ center: coords[0], zoom: 13 });
      }
    };
    if (map._sjReady) apply();
    else map.once("sjready", apply);
  }, [fitKey]);

  return (
    <div className="map-wrap">
      <div className="map" ref={ref} />
      <div className="legend">
        <div className="row"><span className="sw" style={{ background: "#33d08c" }} />Safe</div>
        <div className="row"><span className="sw" style={{ background: "#f0b429" }} />Caution</div>
        <div className="row"><span className="sw" style={{ background: "#ff6150" }} />Danger / hazard</div>
      </div>
    </div>
  );
}

function fc(features) {
  return { type: "FeatureCollection", features };
}
function lineFeature(coords, color, selected) {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: coords },
    properties: { color, selected },
  };
}
