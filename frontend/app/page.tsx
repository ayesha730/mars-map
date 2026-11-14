"use client";

import MarsMap from "@/components/MarsMap";
import { calculateRoute, checkBackendHealth } from "@/lib/api";
import { useEffect, useState } from "react";
import type { RouteRequest, RouteResponse } from "@/types/api";


const initialLayers = [
  {
    id: "elevation",
    name: "Elevation Model",
    detail: "MOLA / MEGDR",
    color: "#e5a35c",
    enabled: true,
  },
  {
    id: "imagery",
    name: "Surface Imagery",
    detail: "Orbital imagery",
    color: "#d77b58",
    enabled: true,
  },
  {
    id: "slope",
    name: "Terrain Slope",
    detail: "Derived terrain layer",
    color: "#e7ca72",
    enabled: false,
  },
  {
    id: "hazards",
    name: "Terrain Constraints",
    detail: "Experimental overlay",
    color: "#e47777",
    enabled: false,
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

  const [latitude_deg, longitude_deg] = parts;

  if (
    latitude_deg < -90 ||
    latitude_deg > 90 ||
    longitude_deg < -180 ||
    longitude_deg > 180
  ) {
    return null;
  }

  return { latitude_deg, longitude_deg };
}

export default function Home() {
  const [layers, setLayers] = useState(initialLayers);
  const [start, setStart] = useState("");
  const [destination, setDestination] = useState("");
  const [message, setMessage] = useState("");
  const [routeResult, setRouteResult] = useState<RouteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedRegion, setSelectedRegion] = useState("jezero_crater");
  const [catalogueExpanded, setCatalogueExpanded] = useState(true);

const regions = [
  {
    id: "jezero_crater",
    name: "Jezero Crater",
  },
  {
    id: "gale_crater",
    name: "Gale Crater",
  },
];
  const [backendOnline, setBackendOnline] = useState(false);
  const [healthChecked, setHealthChecked] = useState(false);

useEffect(() => {
  checkBackendHealth().then((online) => {
    setBackendOnline(online);
    setHealthChecked(true);
  });
}, []);

  function toggleLayer(id: string) {
    setLayers((current) =>
      current.map((layer) =>
        layer.id === id
          ? { ...layer, enabled: !layer.enabled }
          : layer
      )
    );
  }

  async function prepareRoute() {
    setRouteResult(null);
    setMessage("");

    if (!start.trim() || !destination.trim()) {
      setMessage("Enter both starting and destination coordinates.");
      return;
    }

    const startPoint = parseMarsCoordinate(start);
    const destinationPoint = parseMarsCoordinate(destination);

    if (!startPoint || !destinationPoint) {
      setMessage(
        "Invalid coordinates. Use latitude, longitude (example: 18.30, 77.20)."
      );
      return;
    }

   const regionId = selectedRegion;
    if (!regionId) {
      setMessage(
        "Backend region ID is not configured yet. Waiting for the verified region from the backend team."
      );
      return;
    }

    const request: RouteRequest = {
      region_id: regionId,
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
      setMessage("Sending route request to the AresPath backend...");

      const result = await calculateRoute(request);

      setRouteResult(result);
      setMessage("Route calculated successfully.");
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to calculate route. Please try again."
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="app-shell">
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
          <strong>MARS / SURFACE EXPLORATION</strong>
        </div>
      </header>

      <div className="workspace">
        {/* LEFT PANEL: MAP LAYERS */}
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
      }}
    >
      {regions.map((region) => (
        <option key={region.id} value={region.id}>
          {region.name}
        </option>
      ))}
    </select>

    <span style={{ display: "block", marginTop: "8px" }}>
      Region ID: {selectedRegion}
    </span>
  </div>
</div>
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
        }}
      >
        <span>Available datasets</span>
        <strong>0</strong>
      </div>

      <div
        style={{
          padding: "14px",
          border: "1px solid #46515d",
          borderRadius: "8px",
          background: "#17212b",
        }}
      >
        <div style={{ fontSize: "20px", marginBottom: "8px" }}>
          ◈
        </div>

        <strong>No verified terrain layers yet</strong>

        <p style={{ fontSize: "12px", marginTop: "8px" }}>
          No verified datasets have been ingested for this region.
          Layer availability will update when the backend catalogue
          contains verified data.
        </p>
      </div>

      <div style={{ marginTop: "12px", fontSize: "11px" }}>
        SELECTED REGION: {selectedRegion}
      </div>
    </div>
  )}
</div>

          <div className="section-label layer-section-label">
            DATA OVERLAYS
            <span>
              {layers.filter((layer) => layer.enabled).length} ACTIVE
            </span>
          </div>

          <div className="layer-list">
            {layers.map((layer) => (
              <button
                key={layer.id}
                type="button"
                className={`layer-item ${layer.enabled ? "active" : ""}`}
                onClick={() => toggleLayer(layer.id)}
              >
                <span
                  className="layer-color"
                  style={{ backgroundColor: layer.color }}
                />
                <span className="layer-info">
                  <strong>{layer.name}</strong>
                  <small>{layer.detail}</small>
                </span>
                <span className="layer-toggle">
                  {layer.enabled ? "ON" : "OFF"}
                </span>
              </button>
            ))}
          </div>

          <div className="panel-note">
            <span className="note-icon">ⓘ</span>
            <p>
              Layer availability and metadata will be confirmed when
              verified Mars datasets are connected.
            </p>
          </div>

          <div className="sidebar-footer">
            <span className="footer-line" />
            <span>DATA INTEGRITY FIRST</span>
          </div>
        </aside>

        {/* CENTER PANEL: MAP */}
        <section className="map-section">
          <div className="map-toolbar">
            <div>
              <span className="eyebrow">PLANETARY VIEWER / 01</span>
              <h1>Mars surface explorer</h1>
            </div>

            <div className="map-toolbar-right">
              <span className="view-chip">
                <span className="status-dot" /> MAP WORKSPACE
              </span>

              <button
                className="icon-button"
                type="button"
                title="Reset map view"
                onClick={() =>
                  setMessage(
                    "Map view reset. Scientific map integration is still pending."
                  )
                }
              >
                ↗
              </button>
            </div>
          </div>

          <div className="map-viewport">
            <div className="coordinate coordinate-top">
              PLANET: MARS · BODY-FIXED VIEW
            </div>

            <div className="coordinate coordinate-bottom">
              DISPLAY: PREVIEW ONLY · NO SCIENTIFIC DATA LOADED
            </div>

            <MarsMap />

            <div className="map-center-message">
              <span className="preview-tag">VISUAL PLACEHOLDER</span>
              <strong>Scientific map integration is next</strong>
              <span>
                Verified regional terrain data will replace this preview.
              </span>
            </div>

            <div className="map-scale">
              <span>DISPLAY SCALE</span>
              <strong>NOT CALIBRATED</strong>
            </div>
          </div>

          <div className="map-bottom-bar">
            <div>
              <span className="mini-dot" />
              <span>DATA CONNECTION</span>
              <strong>
  {!healthChecked
    ? "Checking..."
    : backendOnline
      ? "Connected"
      : "Offline"}
</strong>
            </div>

            <div>
              <span>COORDINATE SYSTEM</span>
              <strong>Awaiting CRS validation</strong>
            </div>

            <div>
              <span>ROUTE ENGINE</span>
              <strong>Not connected</strong>
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
            Enter Mars coordinates to prepare a surface route request.
            Use latitude, longitude in degrees.
          </div>

          <div className="route-form">
            <label htmlFor="start-point">STARTING POINT</label>

            <div className="field-wrap">
              <span className="field-marker start-marker" />
              <input
                id="start-point"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                placeholder="Example: 18.30, 77.20"
              />
            </div>

            <div className="route-connector">
              <span />
            </div>

            <label htmlFor="destination-point">DESTINATION</label>

            <div className="field-wrap">
              <span className="field-marker end-marker" />
              <input
                id="destination-point"
                value={destination}
                onChange={(event) => setDestination(event.target.value)}
                placeholder="Example: 18.50, 77.40"
              />
            </div>

            <button
              type="button"
              className="primary-button"
              onClick={prepareRoute}
              disabled={isLoading}
            >
              {isLoading ? "CALCULATING ROUTE..." : "CALCULATE ROUTE"}
              <span>→</span>
            </button>

            {message && (
              <div className="form-message" role="status">
                {message}
              </div>
            )}

            {routeResult && (
              <div className="form-message route-result" role="status">
                <h3>ROUTE RESULT</h3>

                <div className="parameter-row">
                  <span>Status</span>
                  <strong>{routeResult.status}</strong>
                </div>

                <div className="parameter-row">
                  <span>Route ID</span>
                  <strong>{routeResult.route_id}</strong>
                </div>

                <div className="parameter-row">
                  <span>Region</span>
                  <strong>{routeResult.region_id}</strong>
                </div>

                <div className="parameter-row">
                  <span>Algorithm</span>
                  <strong>{routeResult.algorithm}</strong>
                </div>

                <div className="parameter-row">
                  <span>Distance</span>
                  <strong>
                    {(routeResult.distance_m / 1000).toFixed(2)} km
                  </strong>
                </div>

                {routeResult.warnings.length > 0 && (
                  <div className="route-warning">
                    <span>⚠</span>
                    <p>{routeResult.warnings.join(" ")}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="section-divider" />

          <div className="section-label">ROUTE PARAMETERS</div>

          <div className="parameter-row">
            <span>Algorithm</span>
            <strong>A* (planned)</strong>
          </div>

          <div className="parameter-row">
            <span>Routing profile</span>
            <strong>Demonstration</strong>
          </div>

          <div className="parameter-row">
            <span>Terrain cost</span>
            <strong>Not configured</strong>
          </div>

          <div className="route-warning">
            <span>⚠</span>
            <p>
              Routes are not yet calculated. No navigation or safety
              claims are made by this preview.
            </p>
          </div>

          <div className="planner-footer">
            <span className="eyebrow">ARESPATH / MVP BUILD</span>
            <strong>Explore with evidence.</strong>
          </div>
        </aside>
      </div>

      <footer className="app-footer">
        <span>ARESPATH © 2026</span>
        <span>RESEARCH & VISUALIZATION PROTOTYPE</span>
        <span>NOT CERTIFIED FOR ASTRONAUT NAVIGATION</span>
      </footer>
    </main>
  );
}