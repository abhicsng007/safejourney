// Decode a Google/Mapbox encoded polyline (polyline5) into [[lng, lat], ...] for MapLibre.
export function decodePolyline(encoded) {
  if (!encoded) return [];
  const coords = [];
  let index = 0,
    lat = 0,
    lng = 0;
  while (index < encoded.length) {
    let result = 0,
      shift = 0,
      b;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;
    result = 0;
    shift = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;
    coords.push([lng / 1e5, lat / 1e5]); // GeoJSON order: [lng, lat]
  }
  return coords;
}

export function bounds(coords) {
  const lngs = coords.map((c) => c[0]);
  const lats = coords.map((c) => c[1]);
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}
