"use client";

import { useEffect, useRef } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";

import "maplibre-gl/dist/maplibre-gl.css";

setWorkerUrl(
  new URL(
    "maplibre-gl/dist/maplibre-gl-worker.mjs",
    import.meta.url,
  ).toString(),
);

type MarsMapProps = {
  selectedRegion: string;
  resetSignal: number;
  onCoordinateSelect: (coordinate: string) => void;
};

type GridFeature = {
  type: "Feature";
  properties: Record<string, never>;
  geometry: {
    type: "LineString";
    coordinates: number[][];
  };
};

const REGION_VIEWS: Record<
  string,
  { center: [number, number]; zoom: number }
> = {
  jezero_crater: {
    center: [77.4, 18.48],
    zoom: 5,
  },
  gale_crater: {
    center: [137.4, -5.4],
    zoom: 5,
  },
};

function createGrid() {
  const features: GridFeature[] = [];

  // Latitude lines
  for (let latitude = -80; latitude <= 80; latitude += 10) {
    const coordinates: number[][] = [];

    for (let longitude = -180; longitude <= 180; longitude += 5) {
      coordinates.push([longitude, latitude]);
    }

    features.push({
      type: "Feature",
      properties: {},
      geometry: {
        type: "LineString",
        coordinates,
      },
    });
  }

  // Longitude lines
  for (let longitude = -180; longitude <= 180; longitude += 10) {
    const coordinates: number[][] = [];

    for (let latitude = -80; latitude <= 80; latitude += 5) {
      coordinates.push([longitude, latitude]);
    }

    features.push({
      type: "Feature",
      properties: {},
      geometry: {
        type: "LineString",
        coordinates,
      },
    });
  }

  return {
    type: "FeatureCollection" as const,
    features,
  };
}

function createRegionMarkers() {
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        properties: { name: "Jezero Crater" },
        geometry: {
          type: "Point" as const,
          coordinates: [77.4, 18.48],
        },
      },
      {
        type: "Feature" as const,
        properties: { name: "Gale Crater" },
        geometry: {
          type: "Point" as const,
          coordinates: [137.4, -5.4],
        },
      },
    ],
  };
}

export default function MarsMap({
  selectedRegion,
  resetSignal,
  onCoordinateSelect,
}: MarsMapProps) {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const onCoordinateSelectRef = useRef(onCoordinateSelect);

  // Keep the latest callback without recreating the map.
  useEffect(() => {
    onCoordinateSelectRef.current = onCoordinateSelect;
  }, [onCoordinateSelect]);

  // Create the map once.
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const initialView =
      REGION_VIEWS[selectedRegion] ?? REGION_VIEWS.jezero_crater;

    const map = new MapLibreMap({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "mars-background",
            type: "background",
            paint: {
              "background-color": "#101923",
            },
          },
        ],
      },
      center: initialView.center,
      zoom: initialView.zoom,
      minZoom: 1,
      maxZoom: 12,
      renderWorldCopies: false,
      attributionControl: false,
    });

    mapRef.current = map;

    map.addControl(
      new NavigationControl({
        showCompass: true,
        showZoom: true,
        visualizePitch: false,
      }),
      "bottom-right",
    );

    // Add coordinate grid and region markers after map loads.
    map.on("load", () => {
      map.addSource("mars-coordinate-grid", {
        type: "geojson",
        data: createGrid(),
      });

      map.addLayer({
        id: "mars-grid-lines",
        type: "line",
        source: "mars-coordinate-grid",
        paint: {
          "line-color": "#526779",
          "line-width": 1,
          "line-opacity": 0.35,
          "line-dasharray": [2, 3],
        },
      });

      map.addSource("mars-region-marker", {
        type: "geojson",
        data: createRegionMarkers(),
      });

      map.addLayer({
        id: "mars-region-points",
        type: "circle",
        source: "mars-region-marker",
        paint: {
          "circle-radius": 7,
          "circle-color": "#e5a35c",
          "circle-stroke-color": "#fff0d4",
          "circle-stroke-width": 2,
        },
      });

      map.addLayer({
        id: "mars-region-labels",
        type: "symbol",
        source: "mars-region-marker",
        layout: {
          "text-field": ["get", "name"],
          "text-size": 11,
          "text-offset": [0, 1.7],
          "text-anchor": "top",
        },
        paint: {
          "text-color": "#f1c58e",
          "text-halo-color": "#101923",
          "text-halo-width": 2,
        },
      });
    });

    // Clicking the map selects a starting coordinate.
    map.on("click", (event) => {
      const latitude = event.lngLat.lat;
      const longitude = event.lngLat.lng;

      onCoordinateSelectRef.current(
        `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`,
      );
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // The map is created once. View changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Move to the selected region or reset the current view.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const view =
      REGION_VIEWS[selectedRegion] ?? REGION_VIEWS.jezero_crater;

    map.flyTo({
      center: view.center,
      zoom: view.zoom,
      duration: resetSignal > 0 ? 900 : 1400,
      essential: true,
    });
  }, [selectedRegion, resetSignal]);

  return (
    <div
      ref={mapContainer}
      className="mars-map-canvas"
      aria-label="Interactive Mars coordinate workspace"
    />
  );
}