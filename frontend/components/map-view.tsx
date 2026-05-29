"use client";
import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import type { Municipality } from "@/lib/types";
import "leaflet/dist/leaflet.css";

interface Props {
  municipalities: Municipality[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

function scoreColor(score: number | null): string {
  if (score === null) return "#475569";
  if (score >= 0.8) return "#f59e0b";
  if (score >= 0.65) return "#10b981";
  if (score >= 0.5) return "#3b82f6";
  return "#64748b";
}

export default function MapView({ municipalities, selectedId, onSelect }: Props) {
  // Fix leaflet default marker icon missing in Next.js
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet");
    delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "/leaflet/marker-icon-2x.png",
      iconUrl: "/leaflet/marker-icon.png",
      shadowUrl: "/leaflet/marker-shadow.png",
    });
  }, []);

  const withCoords = municipalities.filter((m) => m.lat !== null && m.lon !== null);

  return (
    <MapContainer
      center={[12.8797, 121.774]}
      zoom={6}
      className="w-full h-full"
      style={{ background: "#0f172a" }}
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://carto.com/">CARTO</a>'
      />
      {withCoords.map((m) => (
        <CircleMarker
          key={m.id}
          center={[m.lat!, m.lon!]}
          radius={selectedId === m.id ? 8 : 5}
          pathOptions={{
            color: selectedId === m.id ? "#f59e0b" : scoreColor(m.geo_score),
            fillColor: selectedId === m.id ? "#f59e0b" : scoreColor(m.geo_score),
            fillOpacity: 0.8,
            weight: selectedId === m.id ? 2 : 1,
          }}
          eventHandlers={{ click: () => onSelect(m.id) }}
        >
          <Tooltip>
            <div className="text-xs">
              <strong>{m.name}</strong>, {m.province}
              <br />
              Geo Score: {m.geo_score?.toFixed(3) ?? "—"}
            </div>
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
