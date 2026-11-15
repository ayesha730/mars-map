"use client";

import { useEffect, useRef } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  Marker,
  LngLatBounds,
  setWorkerUrl,
  GeoJSONSource,
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

export default function MarsMap({
  selectedRegion = "jezero_crater",
  orthomosaicVisible = true,
  routeResult = null,
  startPoint = null,
  destinationPoint = null,
  onMapClick,
}: MarsMapProps) {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const startMarkerRef = useRef<Marker | null>(null);
  const destMarkerRef = useRef<Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);

  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

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
      minZoom: 2,
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
      // Add Jezero CTX Orthomosaic raster image source
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

      // Add GeoJSON route line source
      map.addSource("active-route-source", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [],
        },
      });

      // Route casing for contrast against terrain imagery
      map.addLayer({
        id: "active-route-casing",
        type: "line",
        source: "active-route-source",
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

      // Active route line in bright mission green
      map.addLayer({
        id: "active-route-line",
        type: "line",
        source: "active-route-source",
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
    });

    // Map click handler
    map.on("click", (e) => {
      if (onMapClickRef.current) {
        onMapClickRef.current({
          latitude: Number(e.lngLat.lat.toFixed(4)),
          longitude: Number(e.lngLat.lng.toFixed(4)),
        });
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

  // 3. Handle Route Updates
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const source = map.getSource("active-route-source") as GeoJSONSource | undefined;
    if (!source || !source.setData) return;

    if (routeResult?.route_geometry?.points && routeResult.route_geometry.points.length > 0) {
      // Scientifically transform each (X, Y) display point in metres back to [lon, lat]
      const coords: [number, number][] = routeResult.route_geometry.points.map((pt) =>
        displayPointToLonLat(pt),
      );

      source.setData({
        type: "Feature",
        properties: {
          distance_m: routeResult.distance_m,
          algorithm: routeResult.algorithm,
        },
        geometry: {
          type: "LineString",
          coordinates: coords,
        },
      });

      // Fit map view to calculated route
      if (coords.length > 1) {
        const bounds = coords.reduce(
          (acc, c) => acc.extend(c),
          new LngLatBounds(coords[0], coords[0]),
        );
        map.fitBounds(bounds, { padding: 60, maxZoom: 15, duration: 1000 });
      }
    } else {
      source.setData({
        type: "FeatureCollection",
        features: [],
      });
    }
  }, [routeResult]);

  // 5. Update Start Marker
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

  // 6. Update Destination Marker
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
