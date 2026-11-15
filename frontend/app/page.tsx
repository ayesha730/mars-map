"use client";

import MarsMap from "@/components/MarsMap";
import {
  calculateRoute,
  checkBackendHealth,
  fetchRegions,
  fetchLayers,
} from "@/lib/api";
import { useEffect, useState, useMemo } from "react";
import type {
  RouteRequest,
  RouteResponse,
  RegionSummary,
  LayerCatalogueEntry,
} from "@/types/api";

const JEZERO_PRESETS = [
  {
    name: "Perseverance Landing Site (Octavia E. Butler)",
    lat: 18.4447,
    lon: 77.4508,
  },
  {
    name: "Jezero Delta Front Scarp",
    lat: 18.4350,
    lon: 77.4000,
  },
  {
    name: "Belva Crater Western Rim",
    lat: 18.5000,
    lon: 77.3700,
  },
  {
    name: "Kodiak Butte Stratigraphic Remnant",
    lat: 18.4100,
    lon: 77.4400,
  },
];

function parseMarsCoordinate(value: string) {
  const parts = value.split(",").map((part) => Number(part.trim()));

  if (
    parts.length !== 2 ||
    parts.some((part) => !Number.isFinite(part))
  ) {
    return null;
  }

  const [latitude, longitude] = parts;

  if (
    latitude < -90 ||
    latitude > 90 ||
    longitude < -180 ||
    longitude > 180
  ) {
    return null;
  }

  return { latitude, longitude };
}

export default function Home() {
  const [start, setStart] = useState("18.4447, 77.4508");
  const [destination, setDestination] = useState("18.4350, 77.4000");
  const [message, setMessage] = useState("");
  const [routeResult, setRouteResult] = useState<RouteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedRegion, setSelectedRegion] = useState("jezero_crater");
  const [catalogueExpanded, setCatalogueExpanded] = useState(true);

  // Real backend data states
  const [regions, setRegions] = useState<RegionSummary[]>([
    {
      region_id: "jezero_crater",
      display_name: "Jezero Crater",
      routing_available: true,
      center_lat_deg: 18.4354,
      center_lon_deg: 77.7900,
      min_lat_deg: 17.5805,
      max_lat_deg: 19.2902,
      min_lon_deg: 76.9974,
      max_lon_deg: 78.5826,
    },
    {
      region_id: "gale_crater",
      display_name: "Gale Crater",
      routing_available: false,
      routing_unavailable_reason: "ROUTING_DATA_UNAVAILABLE",
      center_lat_deg: -4.6,
      center_lon_deg: 137.4,
      min_lat_deg: -5.5,
      max_lat_deg: -3.7,
      min_lon_deg: 136.5,
      max_lon_deg: 138.3,
    },
  ]);

  const [catalogueLayers, setCatalogueLayers] = useState<LayerCatalogueEntry[]>([]);
  const [orthoVisible, setOrthoVisible] = useState(true);
  const [backendOnline, setBackendOnline] = useState(false);
  const [healthChecked, setHealthChecked] = useState(false);

  // Check health and load regions on mount
  useEffect(() => {
    checkBackendHealth().then((online) => {
      setBackendOnline(online);
      setHealthChecked(true);
      if (online) {
        fetchRegions()
          .then((res) => {
            if (Array.isArray(res) && res.length > 0) {
              setRegions(res);
            }
          })
          .catch(() => {});
      }
    });
  }, []);

  // Load layers when selected region changes
  useEffect(() => {
    if (backendOnline) {
      fetchLayers(selectedRegion)
        .then((res) => {
          setCatalogueLayers(res.layers || []);
        })
        .catch(() => {
          setCatalogueLayers([]);
        });
    }
  }, [selectedRegion, backendOnline]);

  const startPoint = useMemo(() => parseMarsCoordinate(start), [start]);
  const destinationPoint = useMemo(() => parseMarsCoordinate(destination), [destination]);

  const currentRegionMeta = useMemo(
    () => regions.find((r) => r.region_id === selectedRegion),
    [regions, selectedRegion],
  );

  function handleMapClick(coords: { latitude: number; longitude: number }) {
    const formatted = `${coords.latitude.toFixed(4)}, ${coords.longitude.toFixed(4)}`;
    if (!start.trim() || (start.trim() && destination.trim())) {
      setStart(formatted);
      setDestination("");
      setRouteResult(null);
      setMessage(`Start point set to (${formatted}) via map click. Click again to set destination.`);
    } else {
      setDestination(formatted);
      setMessage(`Destination set to (${formatted}) via map click. Ready to calculate route.`);
    }
  }

  async function prepareRoute() {
    setRouteResult(null);
    setMessage("");

    if (!start.trim() || !destination.trim()) {
      setMessage("Enter both starting and destination coordinates.");
      return;
    }

    if (!startPoint || !destinationPoint) {
      setMessage("Invalid coordinates. Use latitude, longitude in degrees (e.g. 18.4447, 77.4508).");
      return;
    }

    if (currentRegionMeta && !currentRegionMeta.routing_available) {
      setMessage(
        `Routing is currently unavailable for ${currentRegionMeta.display_name}. ` +
          "Verified DTM terrain data has not yet been ingested for this region.",
      );
      return;
    }

    const request: RouteRequest = {
      region_id: selectedRegion,
      start: startPoint,
      destination: destinationPoint,
      coordinate_reference: {
        body: "Mars",
        latitude_type: "planetocentric",
        longitude_direction: "positive_east",
        longitude_domain: "-180_to_180",
        angular_unit: "degrees",
      },
      routing_profile: "demonstration",
    };

    try {
      setIsLoading(true);
      setMessage("Calculating optimal 3D terrain route using AresPath A* engine...");

      const result = await calculateRoute(request);
      setRouteResult(result);
      setMessage(`Route calculated: ${(result.distance_m / 1000).toFixed(2)} km across Jezero terrain.`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to calculate route. Please try again.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="app-shell">
      {/* TOP BAR */}
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-name">ARESPATH</div>
            <div className="brand-subtitle">
              MARTIAN SURFACE INTELLIGENCE
            </div>
          </div>
        </div>

        <div className="mission-status">
          <span
            className="status-dot"
            style={{
              backgroundColor: !healthChecked
                ? "#e5a35c"
                : backendOnline
                  ? "#55d69e"
                  : "#e47777",
            }}
          />
          {!healthChecked
            ? "CHECKING BACKEND..."
            : backendOnline
              ? "BACKEND ONLINE"
              : "BACKEND OFFLINE"}
        </div>

        <div className="topbar-right">
          <span className="topbar-label">MISSION</span>
          <strong>MARS 2020 / JEZERO BASIN EXPLORATION</strong>
        </div>
      </header>

      <div className="workspace">
        {/* LEFT PANEL: MAP LAYERS & REGIONS */}
        <aside className="panel left-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">WORKSPACE</span>
              <h2>Map layers</h2>
            </div>
            <span className="heading-icon">▤</span>
          </div>

          <div className="section-label">ACTIVE REGION</div>

          <div className="region-card">
            <div className="region-icon">⌖</div>
            <div style={{ width: "100%" }}>
              <strong>SELECT MARS REGION</strong>
              <select
                value={selectedRegion}
                onChange={(event) => {
                  setSelectedRegion(event.target.value);
                  setMessage("");
                  setRouteResult(null);
                }}
                style={{
                  width: "100%",
                  marginTop: "10px",
                  padding: "10px",
                  background: "#17212b",
                  color: "#ffffff",
                  border: "1px solid #46515d",
                  borderRadius: "6px",
                  fontSize: "13px",
                }}
              >
                {regions.map((region) => (
                  <option key={region.region_id} value={region.region_id}>
                    {region.display_name} {region.routing_available ? "✓ (DTM Ready)" : "(Awaiting DTM)"}
                  </option>
                ))}
              </select>

              <span style={{ display: "block", marginTop: "8px", fontSize: "11px", color: "#82909f" }}>
                Region ID: {selectedRegion}
              </span>
            </div>
          </div>

          {/* VERIFIED LAYER CATALOGUE */}
          <div className="catalogue-panel">
            <button
              type="button"
              onClick={() => setCatalogueExpanded((current) => !current)}
              style={{
                width: "100%",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "transparent",
                border: "none",
                color: "inherit",
                cursor: "pointer",
                padding: "8px 0",
              }}
            >
              <strong>VERIFIED LAYER CATALOGUE</strong>
              <span>{catalogueExpanded ? "−" : "+"}</span>
            </button>

            {catalogueExpanded && (
              <div style={{ marginTop: "12px" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginBottom: "12px",
                    fontSize: "12px",
                  }}
                >
                  <span>Available datasets</span>
                  <strong>{catalogueLayers.length > 0 ? catalogueLayers.length : (selectedRegion === "jezero_crater" ? 2 : 0)}</strong>
                </div>

                {selectedRegion === "jezero_crater" ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div
                      style={{
                        padding: "10px",
                        border: "1px solid #34485c",
                        borderRadius: "6px",
                        background: "#141e28",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong style={{ fontSize: "12px", color: "#e5a35c" }}>Jezero CTX DEM (20m)</strong>
                        <span style={{ fontSize: "10px", color: "#55d69e" }}>VERIFIED</span>
                      </div>
                      <p style={{ fontSize: "11px", color: "#82909f", marginTop: "4px", lineHeight: "1.3" }}>
                        USGS/JPL TRN product (DOI: 10.5066/P906QQT8). Ground truth elevation for A* routing.
                      </p>
                    </div>

                    <div
                      style={{
                        padding: "10px",
                        border: "1px solid #34485c",
                        borderRadius: "6px",
                        background: "#141e28",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong style={{ fontSize: "12px", color: "#d77b58" }}>Jezero CTX Ortho (6m)</strong>
                        <span style={{ fontSize: "10px", color: "#55d69e" }}>VERIFIED</span>
                      </div>
                      <p style={{ fontSize: "11px", color: "#82909f", marginTop: "4px", lineHeight: "1.3" }}>
                        USGS/JPL TRN product (DOI: 10.5066/P9GV1ND3). Visual context imagery.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      padding: "14px",
                      border: "1px solid #46515d",
                      borderRadius: "8px",
                      background: "#17212b",
                    }}
                  >
                    <div style={{ fontSize: "20px", marginBottom: "8px" }}>◈</div>
                    <strong>No verified terrain layers yet</strong>
                    <p style={{ fontSize: "12px", marginTop: "8px", color: "#82909f" }}>
                      No verified datasets have been ingested for {selectedRegion}.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* DATA OVERLAYS TOGGLE */}
          <div className="section-label layer-section-label">
            DATA OVERLAYS
            <span>{orthoVisible ? "1 ACTIVE" : "0 ACTIVE"}</span>
          </div>

          <div className="layer-list">
            <button
              type="button"
              className={`layer-item ${orthoVisible ? "active" : ""}`}
              onClick={() => setOrthoVisible((v) => !v)}
            >
              <span className="layer-color" style={{ backgroundColor: "#d77b58" }} />
              <span className="layer-info">
                <strong>Surface Imagery (CTX 6m)</strong>
                <small>USGS/JPL TRN Orthomosaic</small>
              </span>
              <span className="layer-toggle">{orthoVisible ? "ON" : "OFF"}</span>
            </button>
          </div>

          <div className="panel-note">
            <span className="note-icon">ⓘ</span>
            <p>
              Imagery and elevation layers use IAU 2015 Mars sphere equirectangular projection
              at standard parallel 18.4663°N.
            </p>
          </div>

          <div className="sidebar-footer">
            <span className="footer-line" />
            <span>DATA INTEGRITY FIRST</span>
          </div>
        </aside>

        {/* CENTER PANEL: MARS MAP */}
        <section className="map-section">
          <div className="map-toolbar">
            <div>
              <span className="eyebrow">PLANETARY VIEWER / 01</span>
              <h1>Mars surface explorer — Jezero Basin</h1>
            </div>

            <div className="map-toolbar-right">
              <span className="view-chip">
                <span className="status-dot" style={{ backgroundColor: "#55d69e" }} />
                {selectedRegion === "jezero_crater" ? "CTX 6M ORTHO ACTIVE" : "BASEMAP VIEW"}
              </span>

              <button
                className="icon-button"
                type="button"
                title="Reset map view to Jezero Crater"
                onClick={() => {
                  setSelectedRegion("jezero_crater");
                  setMessage("Map view recentered on Jezero Crater basin.");
                }}
              >
                ↗
              </button>
            </div>
          </div>

          <div className="map-viewport">
            <div className="coordinate coordinate-top">
              PLANET: MARS · IAU 2015 SPHERE · DATUM: IAU:2015:49900
            </div>

            <div className="coordinate coordinate-bottom">
              {selectedRegion === "jezero_crater"
                ? "DISPLAY: USGS/JPL CTX ORTHOMOSAIC (6M) + CTX DTM (20M) · VERIFIED"
                : "DISPLAY: PREVIEW ONLY · AWAITING REGIONAL DTM"}
            </div>

            <MarsMap
              selectedRegion={selectedRegion}
              orthomosaicVisible={orthoVisible}
              routeResult={routeResult}
              startPoint={startPoint}
              destinationPoint={destinationPoint}
              onMapClick={handleMapClick}
            />

            <div className="map-scale">
              <span>PROJECTION</span>
              <strong>EQC (18.4663°N)</strong>
            </div>
          </div>

          <div className="map-bottom-bar">
            <div>
              <span
                className="mini-dot"
                style={{ backgroundColor: backendOnline ? "#55d69e" : "#e47777" }}
              />
              <span>DATA CONNECTION</span>
              <strong>{backendOnline ? "Connected" : "Offline"}</strong>
            </div>

            <div>
              <span>COORDINATE SYSTEM</span>
              <strong>Equirectangular Mars 2000 (R=3,396,190m)</strong>
            </div>

            <div>
              <span>ROUTE ENGINE</span>
              <strong>{currentRegionMeta?.routing_available ? "A* 3D Euclidean (Jezero CTX)" : "Unavailable"}</strong>
            </div>
          </div>
        </section>

        {/* RIGHT PANEL: WALK PLANNER */}
        <aside className="panel right-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">NAVIGATION TOOLS</span>
              <h2>Walk planner</h2>
            </div>
            <span className="heading-icon">⌁</span>
          </div>

          <div className="planner-intro">
            Click on the map or select landmark presets to plan surface traversal.
            Coordinates are in degrees (Lat °N, Lon °E).
          </div>

          {/* LANDMARK PRESETS */}
          {selectedRegion === "jezero_crater" && (
            <div style={{ marginBottom: "16px" }}>
              <div className="section-label" style={{ marginBottom: "8px" }}>
                JEZERO LANDMARK PRESETS
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
                {JEZERO_PRESETS.map((preset) => (
                  <button
                    key={preset.name}
                    type="button"
                    onClick={() => {
                      if (!start.trim() || (start.trim() && destination.trim())) {
                        setStart(`${preset.lat.toFixed(4)}, ${preset.lon.toFixed(4)}`);
                        setDestination("");
                        setRouteResult(null);
                        setMessage(`Start set to ${preset.name}`);
                      } else {
                        setDestination(`${preset.lat.toFixed(4)}, ${preset.lon.toFixed(4)}`);
                        setMessage(`Destination set to ${preset.name}`);
                      }
                    }}
                    style={{
                      background: "#17212b",
                      border: "1px solid #34485c",
                      borderRadius: "5px",
                      padding: "7px 9px",
                      color: "#edf2f7",
                      fontSize: "11px",
                      textAlign: "left",
                      lineHeight: "1.2",
                    }}
                  >
                    <span style={{ color: "#e5a35c", fontWeight: "700", display: "block" }}>
                      {preset.name.split(" ")[0]}
                    </span>
                    <span style={{ fontSize: "10px", color: "#82909f" }}>
                      {preset.lat.toFixed(3)}°N, {preset.lon.toFixed(3)}°E
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="route-form">
            <label htmlFor="start-point">STARTING POINT (LAT, LON)</label>
            <div className="field-wrap">
              <span className="field-marker start-marker" />
              <input
                id="start-point"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                placeholder="Example: 18.4447, 77.4508"
              />
            </div>

            <div className="route-connector">
              <span />
            </div>

            <label htmlFor="destination-point">DESTINATION (LAT, LON)</label>
            <div className="field-wrap">
              <span className="field-marker end-marker" />
              <input
                id="destination-point"
                value={destination}
                onChange={(event) => setDestination(event.target.value)}
                placeholder="Example: 18.4350, 77.4000"
              />
            </div>

            <button
              type="button"
              className="primary-button"
              onClick={prepareRoute}
              disabled={isLoading || !backendOnline}
            >
              {isLoading ? "CALCULATING A* ROUTE..." : "CALCULATE ROUTE"}
              <span>→</span>
            </button>

            {message && (
              <div className="form-message" role="status">
                {message}
              </div>
            )}

            {routeResult && (
              <div className="form-message route-result" role="status">
                <h3 style={{ color: "#55d69e", marginBottom: "8px" }}>ROUTE CALCULATED</h3>

                <div className="parameter-row">
                  <span>Status</span>
                  <strong style={{ color: "#55d69e" }}>OPTIMAL PATH</strong>
                </div>

                <div className="parameter-row">
                  <span>Total Distance</span>
                  <strong>
                    {(routeResult.distance_m / 1000).toFixed(2)} km ({routeResult.distance_m.toFixed(0)} m)
                  </strong>
                </div>

                <div className="parameter-row">
                  <span>Waypoints</span>
                  <strong>{routeResult.route_geometry.points.length} nodes</strong>
                </div>

                <div className="parameter-row">
                  <span>Algorithm</span>
                  <strong style={{ fontSize: "11px" }}>{routeResult.algorithm}</strong>
                </div>

                <div className="parameter-row">
                  <span>Coordinate Space</span>
                  <strong style={{ fontSize: "11px" }}>{routeResult.route_geometry.coordinate_space}</strong>
                </div>

                {routeResult.warnings && routeResult.warnings.length > 0 && (
                  <div className="route-warning" style={{ marginTop: "10px" }}>
                    <span>⚠</span>
                    <p>{routeResult.warnings.join(" ")}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="section-divider" />

          <div className="section-label">ROUTE SPECIFICATIONS</div>

          <div className="parameter-row">
            <span>Algorithm</span>
            <strong>Deterministic 8-way A*</strong>
          </div>

          <div className="parameter-row">
            <span>Terrain Model</span>
            <strong>Jezero CTX 20m DTM</strong>
          </div>

          <div className="parameter-row">
            <span>Cost Function</span>
            <strong>3D Euclidean Distance</strong>
          </div>

          <div className="parameter-row">
            <span>Safety Rule</span>
            <strong>Corner-Cutting Prevention</strong>
          </div>

          <div className="planner-footer">
            <span className="eyebrow">ARESPATH / HACKATHON MVP</span>
            <strong>Interplanetary Survival Guide: Martian Map</strong>
          </div>
        </aside>
      </div>

      <footer className="app-footer">
        <span>ARESPATH © 2026</span>
        <span>RESEARCH & VISUALIZATION PROTOTYPE</span>
        <span>NOT CERTIFIED FOR ASTRONAUT FLIGHT OPERATIONS</span>
      </footer>
    </main>
  );
}
