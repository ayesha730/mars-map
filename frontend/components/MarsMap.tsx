"use client";

import { useEffect, useRef } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";

// Configure the MapLibre worker for Next.js
setWorkerUrl(
  new URL(
    "maplibre-gl/dist/maplibre-gl-worker.mjs",
    import.meta.url,
  ).toString(),
);

export default function MarsMap() {
  const mapContainer = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!mapContainer.current) return;

    const map = new MapLibreMap({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "map-background",
            type: "background",
            paint: {
              "background-color": "#0b121a",
            },
          },
        ],
      },
      center: [0, 0],
      zoom: 1,
      minZoom: 0,
      maxZoom: 8,
      renderWorldCopies: false,
      attributionControl: false,
    });

    map.addControl(
      new NavigationControl({
        showCompass: true,
        showZoom: true,
        visualizePitch: false,
      }),
      "bottom-right",
    );

    return () => {
      map.remove();
    };
  }, []);

  return (
    <div
      ref={mapContainer}
      className="mars-map-canvas"
      aria-label="Interactive planetary map workspace"
    />
  );
}