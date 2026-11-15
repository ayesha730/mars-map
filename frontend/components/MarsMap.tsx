"use client";

import { useEffect, useRef, useMemo } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  Marker,
  LngLatBounds,
  setWorkerUrl,
  type GeoJSONSource,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  displayPointToLonLat,
  getRasterPreviewUrl,
} from "@/lib/api";
import type { RouteResponse } from "@/types/api";

// Configure MapLibre web worker for Next.js
setWorkerUrl(
  new URL(
    "maplibre-gl/dist/maplibre-gl-worker.mjs",
    import.meta.url,
  ).toString(),
);

// Jezero Crater Orthomosaic coverage bounds (USGS/JPL TRN product)
export const JEZERO_ORTHO_BOUNDS = {
  min_lon: 77.1605,
  min_lat: 18.2110,
  max_lon: 77.6992,
  max_lat: 18.7212,
};

export const REGION_CENTERS: Record<string, { center: [number, number]; zoom: number }> = {
  jezero_crater: { center: [77.43, 18.45], zoom: 11 },
  gale_crater: { center: [137.4, -4.6], zoom: 10 },
};

export interface MarsMapProps {
  selectedRegion?: string;
  orthomosaicVisible?: boolean;
  routeResult?: RouteResponse | null;
  startPoint?: { latitude: number; longitude: number } | null;
  destinationPoint?: { latitude: number; longitude: number } | null;
  onMapClick?: (coords: { latitude: number; longitude: number }) => void;
  // Ayesha PR #2 compatibility props
  resetSignal?: number;
  onCoordinateSelect?: (coordinate: string) => void;
  routeCoordinates?: [number, number][];
}

interface GridFeature {
  type: "Feature";
  properties: Record<string, unknown>;
  geometry: {
    type: "LineString";
    coordinates: number[][];
  };
}

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
      geometry: { type: "LineString", coordinates },
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
      geometry: { type: "LineString", coordinates },
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
        geometry: { type: "Point" as const, coordinates: [77.43, 18.45] },
      },
      {
        type: "Feature" as const,
        properties: { name: "Gale Crater" },
        geometry: { type: "Point" as const, coordinates: [137.4, -4.6] },
      },
    ],
  };
}

function createMarkerElement(label: string, color: string, title: string): HTMLDivElement {
  const el = document.createElement("div");
  el.className = "ares-map-marker";
  el.title = title;
  el.style.width = "28px";
  el.style.height = "28px";
  el.style.borderRadius = "50%";
  el.style.backgroundColor = color;
  el.style.color = "#0b121a";
  el.style.display = "flex";
  el.style.alignItems = "center";
  el.style.justifyContent = "center";
  el.style.fontWeight = "800";
  el.style.fontSize = "13px";
  el.style.border = "2px solid #ffffff";
  el.style.boxShadow = "0 2px 8px rgba(0,0,0,0.6)";
  el.style.cursor = "pointer";
  el.innerText = label;
  return el;
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
    padding: 80,
    maxZoom: 15,
    duration: 1000,
  });
}

export default function MarsMap({
  selectedRegion = "jezero_crater",
  orthomosaicVisible = true,
  routeResult = null,
  startPoint = null,
  destinationPoint = null,
  onMapClick,
  resetSignal = 0,
  onCoordinateSelect,
  routeCoordinates,
}: MarsMapProps) {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const startMarkerRef = useRef<Marker | null>(null);
  const destMarkerRef = useRef<Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const onCoordinateSelectRef = useRef(onCoordinateSelect);

  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  useEffect(() => {
    onCoordinateSelectRef.current = onCoordinateSelect;
  }, [onCoordinateSelect]);

  // Derive active route coordinates from either routeCoordinates prop or routeResult
  const activeCoordinates: [number, number][] = useMemo(() => {
    if (routeCoordinates && routeCoordinates.length > 0) {
      return routeCoordinates;
    }
    if (routeResult?.route_geometry?.points && routeResult.route_geometry.points.length > 0) {
      return routeResult.route_geometry.points.map((pt) => displayPointToLonLat(pt));
    }
    return [];
  }, [routeCoordinates, routeResult]);

  // 1. Initialize Map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const initialCenter = REGION_CENTERS[selectedRegion]?.center || [77.43, 18.45];
    const initialZoom = REGION_CENTERS[selectedRegion]?.zoom || 11;

    const map = new MapLibreMap({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "mars-basemap",
            type: "background",
            paint: {
              "background-color": "#0b121a",
            },
          },
        ],
      },
      center: initialCenter,
      zoom: initialZoom,
      minZoom: 1,
      maxZoom: 18,
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

    map.on("load", () => {
      // Coordinate grid lines
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

      // Jezero CTX Orthomosaic raster image source (USGS/JPL TRN 6m)
      const previewUrl = getRasterPreviewUrl("jezero_ctx_orthomosaic_6m", {
        ...JEZERO_ORTHO_BOUNDS,
        max_dimension: 2048,
      });

      map.addSource("jezero-ortho-source", {
        type: "image",
        url: previewUrl,
        coordinates: [
          [JEZERO_ORTHO_BOUNDS.min_lon, JEZERO_ORTHO_BOUNDS.max_lat], // Top-Left
          [JEZERO_ORTHO_BOUNDS.max_lon, JEZERO_ORTHO_BOUNDS.max_lat], // Top-Right
          [JEZERO_ORTHO_BOUNDS.max_lon, JEZERO_ORTHO_BOUNDS.min_lat], // Bottom-Right
          [JEZERO_ORTHO_BOUNDS.min_lon, JEZERO_ORTHO_BOUNDS.min_lat], // Bottom-Left
        ],
      });

      map.addLayer({
        id: "jezero-ortho-layer",
        type: "raster",
        source: "jezero-ortho-source",
        layout: {
          visibility: orthomosaicVisible && selectedRegion === "jezero_crater" ? "visible" : "none",
        },
        paint: {
          "raster-opacity": 0.95,
          "raster-fade-duration": 0,
        },
      });

      // Mars region markers
      map.addSource("mars-region-marker", {
        type: "geojson",
        data: createRegionMarkers(),
      });

      map.addLayer({
        id: "mars-region-points",
        type: "circle",
        source: "mars-region-marker",
        paint: {
          "circle-radius": 6,
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
          "text-offset": [0, 1.2],
          "text-anchor": "top",
        },
        paint: {
          "text-color": "#e5a35c",
          "text-halo-color": "#0b121a",
          "text-halo-width": 1.5,
        },
      });

      // Route casing for high contrast against imagery
      map.addSource("mars-computed-route", {
        type: "geojson",
        data: createRouteFeature(activeCoordinates),
      });

      map.addLayer({
        id: "mars-route-casing",
        type: "line",
        source: "mars-computed-route",
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
        paint: {
          "line-color": "#0b121a",
          "line-width": 6,
          "line-opacity": 0.85,
        },
      });

      // Active computed route line in high-visibility mission green
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
          "line-width": 3.5,
          "line-opacity": 1.0,
        },
      });

      // Route start/destination markers layer
      map.addSource("mars-route-markers", {
        type: "geojson",
        data: createRouteMarkers(activeCoordinates),
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

      if (activeCoordinates.length >= 2) {
        fitMapToRoute(map, activeCoordinates);
      }
    });

    // Map click handler (supports both object and string coordinate subscribers)
    map.on("click", (e) => {
      const lat = Number(e.lngLat.lat.toFixed(4));
      const lon = Number(e.lngLat.lng.toFixed(4));

      if (onMapClickRef.current) {
        onMapClickRef.current({ latitude: lat, longitude: lon });
      }

      if (onCoordinateSelectRef.current) {
        onCoordinateSelectRef.current(`${lat.toFixed(5)}, ${lon.toFixed(5)}`);
      }
    });

    map.getCanvas().style.cursor = "crosshair";
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. Handle Region & Orthomosaic Layer Visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const target = REGION_CENTERS[selectedRegion];
    if (target) {
      map.flyTo({
        center: target.center,
        zoom: target.zoom,
        essential: true,
      });
    }

    if (map.getLayer("jezero-ortho-layer")) {
      const isVisible = orthomosaicVisible && selectedRegion === "jezero_crater";
      map.setLayoutProperty("jezero-ortho-layer", "visibility", isVisible ? "visible" : "none");
    }
  }, [selectedRegion, orthomosaicVisible]);

  // 3. Reset view signal
  useEffect(() => {
    if (resetSignal <= 0) return;
    const map = mapRef.current;
    if (!map) return;

    const target = REGION_CENTERS[selectedRegion];
    if (target) {
      map.flyTo({
        center: target.center,
        zoom: target.zoom,
        essential: true,
      });
    }
  }, [resetSignal, selectedRegion]);

  // 4. Update Route Line & Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const routeSource = map.getSource("mars-computed-route") as GeoJSONSource | undefined;
    const markerSource = map.getSource("mars-route-markers") as GeoJSONSource | undefined;

    if (activeCoordinates.length > 0) {
      routeSource?.setData(createRouteFeature(activeCoordinates));
      markerSource?.setData(createRouteMarkers(activeCoordinates));
      if (activeCoordinates.length >= 2) {
        fitMapToRoute(map, activeCoordinates);
      }
    } else {
      routeSource?.setData({ type: "FeatureCollection", features: [] });
      markerSource?.setData({ type: "FeatureCollection", features: [] });
    }
  }, [activeCoordinates]);

  // 5. Update HTML Start Marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (startPoint) {
      if (!startMarkerRef.current) {
        const el = createMarkerElement("A", "#55d69e", "Start Point");
        startMarkerRef.current = new Marker({ element: el })
          .setLngLat([startPoint.longitude, startPoint.latitude])
          .addTo(map);
      } else {
        startMarkerRef.current.setLngLat([startPoint.longitude, startPoint.latitude]);
      }
    } else if (startMarkerRef.current) {
      startMarkerRef.current.remove();
      startMarkerRef.current = null;
    }
  }, [startPoint]);

  // 6. Update HTML Destination Marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (destinationPoint) {
      if (!destMarkerRef.current) {
        const el = createMarkerElement("B", "#e47777", "Destination");
        destMarkerRef.current = new Marker({ element: el })
          .setLngLat([destinationPoint.longitude, destinationPoint.latitude])
          .addTo(map);
      } else {
        destMarkerRef.current.setLngLat([
          destinationPoint.longitude,
          destinationPoint.latitude,
        ]);
      }
    } else if (destMarkerRef.current) {
      destMarkerRef.current.remove();
      destMarkerRef.current = null;
    }
  }, [destinationPoint]);

  return (
    <div
      ref={mapContainer}
      className="mars-map-canvas"
      aria-label="Interactive planetary map workspace"
    />
  );
}
