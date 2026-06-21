"use client";

import { useEffect } from "react";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
} from "react-leaflet";
import type { FeatureCollection } from "geojson";
import type { LatLngBoundsExpression } from "leaflet";
import L from "leaflet";

export type RepresentativeMapGeometry = {
  state: string;
  congressional_district: string;
  house_geometry: FeatureCollection;
  state_geometry: FeatureCollection;
  warning?: string | null;
};

type RepresentativeMapProps = {
  geometry: RepresentativeMapGeometry;
  districtParty?: string | null;
};

export default function RepresentativeMap({ 
    geometry,
    districtParty,
 }: RepresentativeMapProps) {
  const hasDistrict = hasFeatures(geometry.house_geometry);
  const hasState = hasFeatures(geometry.state_geometry);
  const districtStyle = partyMapStyle(districtParty);

  if (!hasDistrict && !hasState) {
    return (
      <div className="rounded-2xl border border-line bg-panel p-4 text-sm text-slate-600">
        Map boundary data is unavailable for this profile.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-white">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Your Congressional Map
          </h3>
          <p className="text-xs text-slate-500">
            {geometry.state}
            {geometry.congressional_district
              ? `-${geometry.congressional_district}`
              : ""}{" "}
            highlighted from Census TIGERweb boundaries.
          </p>
        </div>
      </div>

      <div className="h-[360px]">
        <MapContainer
          center={[39.8283, -98.5795]}
          zoom={4}
          scrollWheelZoom={false}
          className="h-full w-full"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {hasState ? (
            <GeoJSON
              key={`state-${geometry.state}`}
              data={geometry.state_geometry}
              style={{
                color: "#64748b",
                weight: 1,
                fillColor: "#e2e8f0",
                fillOpacity: 0.15,
              }}
            />
          ) : null}

          {hasDistrict ? (
            <GeoJSON
                key={`district-${geometry.state}-${geometry.congressional_district}-${districtParty ?? "unknown"}`}
                data={geometry.house_geometry}
                style={districtStyle}
            />
          ) : null}

          <FitToGeometry
            primary={geometry.house_geometry}
            fallback={geometry.state_geometry}
          />
        </MapContainer>
      </div>

      {geometry.warning ? (
        <div className="border-t border-line bg-amber-50 px-4 py-3 text-xs text-amber-800">
          {geometry.warning}
        </div>
      ) : null}
    </div>
  );
}

function FitToGeometry({
  primary,
  fallback,
}: {
  primary: FeatureCollection;
  fallback: FeatureCollection;
}) {
  const map = useMap();

  useEffect(() => {
    const target = hasFeatures(primary) ? primary : fallback;

    if (!hasFeatures(target)) {
      return;
    }

    const bounds = geoJsonBounds(target);

    if (bounds) {
      map.fitBounds(bounds, {
        padding: [24, 24],
        maxZoom: 9,
      });
    }
  }, [fallback, map, primary]);

  return null;
}

function hasFeatures(collection?: FeatureCollection | null) {
  return Boolean(collection?.features?.length);
}

function geoJsonBounds(collection: FeatureCollection): LatLngBoundsExpression | null {
  try {
    const layer = L.geoJSON(collection);
    const bounds = layer.getBounds();

    if (!bounds.isValid()) {
      return null;
    }

    return bounds;
  } catch {
    return null;
  }
}

function partyMapStyle(party?: string | null) {
  const normalized = (party ?? "").trim().toLowerCase();

  if (party === "R" || normalized.includes("republican")) {
    return {
      color: "#dc2626",
      weight: 3,
      fillColor: "#ef4444",
      fillOpacity: 0.28,
    };
  }

  if (party === "D" || normalized.includes("democrat")) {
    return {
      color: "#2563eb",
      weight: 3,
      fillColor: "#3b82f6",
      fillOpacity: 0.28,
    };
  }

  if (party === "I" || normalized.includes("independent")) {
    return {
      color: "#ca8a04",
      weight: 3,
      fillColor: "#eab308",
      fillOpacity: 0.28,
    };
  }

  return {
    color: "#475569",
    weight: 3,
    fillColor: "#94a3b8",
    fillOpacity: 0.24,
  };
}