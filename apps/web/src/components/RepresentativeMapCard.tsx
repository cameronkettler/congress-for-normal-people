"use client";

import dynamic from "next/dynamic";
import type { RepresentativeMapGeometry } from "./RepresentativeMap";

const RepresentativeMap = dynamic(() => import("./RepresentativeMap"), {
  ssr: false,
  loading: () => (
    <div className="rounded-2xl border border-line bg-panel p-4 text-sm text-slate-600">
      Loading map...
    </div>
  ),
});

export default function RepresentativeMapCard({
  geometry,
  districtParty,
}: {
  geometry: RepresentativeMapGeometry;
  districtParty?: string | null;
}) {
  return <RepresentativeMap geometry={geometry} districtParty={districtParty} />;
}