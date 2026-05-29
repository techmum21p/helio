"use client";
import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip } from "react-leaflet";
import type { RunResult } from "@/lib/types";
import { scoreColor, scoreRadius } from "@/lib/score-color";
import "leaflet/dist/leaflet.css";

interface Props {
  results: RunResult[];
  center?: [number, number];
}

export default function RunMapView({ results, center = [12.8797, 121.774] }: Props) {
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet");
    delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "/leaflet/marker-icon-2x.png",
      iconUrl:        "/leaflet/marker-icon.png",
      shadowUrl:      "/leaflet/marker-shadow.png",
    });
  }, []);

  const withCoords = results.filter((r) => r.lat !== null && r.lon !== null);

  return (
    <MapContainer center={center} zoom={7} className="w-full h-full">
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
      />
      {withCoords.map((r) => {
        const color  = scoreColor(r.final_score);
        const radius = scoreRadius(r.final_score);
        return (
          <CircleMarker
            key={r.municipality_id}
            center={[r.lat!, r.lon!]}
            radius={radius}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.75, weight: 1.5 }}
          >
            <Popup>
              <b>{r.municipality_name}</b><br />Score: {r.final_score.toFixed(3)}
            </Popup>
            <Tooltip>{r.municipality_name}: {r.final_score.toFixed(3)}</Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
