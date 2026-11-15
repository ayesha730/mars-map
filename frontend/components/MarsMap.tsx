"use client";

import { useEffect, useRef } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  LngLatBounds,
  setWorkerUrl,
  type GeoJSONSource,
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
  routeCoordinates: [number, number][];
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

function createRouteFeature(coordinates: [number, number][]) {
  return {
    type: "FeatureCollection" as const,
    features:
      coordinates.length >= 2
        ? [
            {
              type: "Feature" as const,
              properties: {},
              geometry: {
                type: "LineString" as const,
                coordinates,
              },
            },
          ]
        : [],
  };
}

function createRouteMarkers(coordinates: [number, number][]) {
  if (coordinates.length === 0) {
    return {
      type: "FeatureCollection" as const,
      features: [],
    };
  }

  const features = [
    {
      type: "Feature" as const,
      properties: {
        kind: "start",
        label: "START",
      },
      geometry: {
        type: "Point" as const,
        coordinates: coordinates[0],
      },
    },
  ];

  if (coordinates.length > 1) {
    features.push({
      type: "Feature" as const,
      properties: {
        kind: "destination",
        label: "DESTINATION",
      },
      geometry: {
        type: "Point" as const,
        coordinates: coordinates[coordinates.length - 1],
      },
    });
  }

  return {
    type: "FeatureCollection" as const,
    features,
  };
}

function fitMapToRoute(
  map: MapLibreMap,
  coordinates: [number, number][],
) {
  if (coordinates.length < 2) return;

  const bounds = new LngLatBounds(
    coordinates[0],
    coordinates[0],
  );

  for (const coordinate of coordinates.slice(1)) {
    bounds.extend(coordinate);
  }

  map.fitBounds(bounds, {
    padding: 90,
    maxZoom: 14,
    duration: 1000,
  });
}

export default function MarsMap({
  selectedRegion,
  resetSignal,
  onCoordinateSelect,
  routeCoordinates,
}: MarsMapProps) {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  const onCoordinateSelectRef = useRef(onCoordinateSelect);
  const routeCoordinatesRef = useRef(routeCoordinates);

  useEffect(() => {
    onCoordinateSelectRef.current = onCoordinateSelect;
  }, [onCoordinateSelect]);

  // Keep the displayed route synchronized with the latest route response.
  useEffect(() => {
    routeCoordinatesRef.current = routeCoordinates;

    const map = mapRef.current;

    if (!map || !map.isStyleLoaded()) return;

    const routeSource = map.getSource(
      "mars-computed-route",
    ) as GeoJSONSource | undefined;

    const markerSource = map.getSource(
      "mars-route-markers",
    ) as GeoJSONSource | undefined;

    routeSource?.setData(createRouteFeature(routeCoordinates));
    markerSource?.setData(createRouteMarkers(routeCoordinates));

    if (routeCoordinates.length >= 2) {
      fitMapToRoute(map, routeCoordinates);
    }
  }, [routeCoordinates]);

  // Create the MapLibre map once.
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
      maxZoom: 16,
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

    map.on("load", () => {
      // Coordinate grid.
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

      // Mars region markers.
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

      // A* computed route.
      map.addSource("mars-computed-route", {
        type: "geojson",
        data: createRouteFeature(routeCoordinatesRef.current),
      });

      map.addLayer({
        id: "mars-route-line",
        type: "line",
        source: "mars-computed-route",
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
        paint: {
          "line-color": "#55d69e",
          "line-width": 4,
          "line-opacity": 0.95,
        },
      });

      // Route start and destination markers.
      map.addSource("mars-route-markers", {
        type: "geojson",
        data: createRouteMarkers(routeCoordinatesRef.current),
      });

      map.addLayer({
        id: "mars-route-marker-circles",
        type: "circle",
        source: "mars-route-markers",
        paint: {
          "circle-radius": 7,
          "circle-color": [
            "match",
            ["get", "kind"],
            "start",
            "#55d69e",
            "destination",
            "#e47777",
            "#ffffff",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });

      map.addLayer({
        id: "mars-route-marker-labels",
        type: "symbol",
        source: "mars-route-markers",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 10,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "#101923",
          "text-halo-width": 2,
        },
      });

      // If a route was received before the map finished loading,
      // zoom to it now.
      if (routeCoordinatesRef.current.length >= 2) {
        fitMapToRoute(map, routeCoordinatesRef.current);
      }
    });

    // Map click returns planetocentric latitude, longitude.
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
    // Map instance is created once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fly to the selected region or reset its view.
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