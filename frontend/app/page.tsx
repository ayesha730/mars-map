"use client";

import MarsMap from "@/components/MarsMap";
import {
  calculateRoute,
  checkBackendHealth,
  getRegions,
  getRegionLayers,
} from "@/lib/api";
import { useEffect, useRef, useState } from "react";
import type {
  MarsCoordinate,
  MarsRegion,
  MarsLayer,
  LayersResponse,
  RouteRequest,
  RouteResponse,
} from "@/types/api";

type LayerView = MarsLayer & {
  enabled: boolean;
};

type MapSelectionTarget = "start" | "destination";

type BackendStatusType =
  | "idle"
  | "loading"
  | "success"
  | "error";

type BackendStatus = {
  type: BackendStatusType;
  message: string;
};

function parseMarsCoordinate(value: string): MarsCoordinate | null {
  const parts = value.split(",");

  if (
    parts.length !== 2 ||
    parts.some((part) => part.trim() === "")
  ) {
    return null;
  }

  const latitude = Number(parts[0].trim());
  const longitude = Number(parts[1].trim());

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return null;
  }

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

function getLayerColor(type: MarsLayer["layer_type"]): string {
  const colors: Record<MarsLayer["layer_type"], string> = {
    dem: "#e5a35c",
    orthoimage: "#d77b58",
    slope: "#e7ca72",
    hazard: "#e47777",
    geologic: "#9e91d5",
    custom: "#76b7c9",
  };

  return colors[type] || "#a0a0a0";
}

export default function Home() {
  // Region state
  const [regions, setRegions] = useState<MarsRegion[]>([]);
  const [selectedRegion, setSelectedRegion] =
    useState("jezero_crater");
  const [regionsLoading, setRegionsLoading] = useState(true);
  const [regionError, setRegionError] = useState("");

  // Interactive map state
  const [mapResetSignal, setMapResetSignal] = useState(0);
  const [mapCoordinate, setMapCoordinate] = useState("");
  const [nextMapSelection, setNextMapSelection] =
    useState<MapSelectionTarget>("start");

  // Layer catalogue state
  const [layers, setLayers] = useState<LayerView[]>([]);
  const [catalogue, setCatalogue] =
    useState<LayersResponse | null>(null);
  const [layersLoading, setLayersLoading] = useState(false);
  const [layerError, setLayerError] = useState("");
  const [catalogueExpanded, setCatalogueExpanded] = useState(true);

  // Backend state
  const [backendOnline, setBackendOnline] = useState(false);
  const [healthChecked, setHealthChecked] = useState(false);

  // Route planner state
  const [start, setStart] = useState("");
  const [destination, setDestination] = useState("");
  const [message, setMessage] = useState("");
  const [routeResult, setRouteResult] =
    useState<RouteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Dedicated backend request status
  const [backendStatus, setBackendStatus] =
    useState<BackendStatus>({
      type: "idle",
      message: "Ready to calculate a Mars surface route.",
    });

  // Synchronous lock to prevent duplicate route requests.
  const routeRequestInFlight = useRef(false);

  // Check backend and fetch available regions
  useEffect(() => {
    let active = true;

    async function initializeBackend() {
      const online = await checkBackendHealth();

      if (!active) return;

      setBackendOnline(online);
      setHealthChecked(true);

      try {
        setRegionsLoading(true);
        setRegionError("");

        const data = await getRegions();

        if (!active) return;

        setRegions(data);

        if (data.length > 0) {
          setSelectedRegion((current) =>
            data.some((region) => region.region_id === current)
              ? current
              : data[0].region_id
          );
        } else {
          setSelectedRegion("");
          setRegionError("No Mars regions are currently registered.");
        }
      } catch (error) {
        if (!active) return;

        setRegionError(
          error instanceof Error
            ? error.message
            : "Unable to load Mars regions."
        );
      } finally {
        if (active) {
          setRegionsLoading(false);
        }
      }
    }

    initializeBackend();

    return () => {
      active = false;
    };
  }, []);

  // Fetch layer catalogue whenever selected region changes
  useEffect(() => {
    if (!selectedRegion) {
      setLayers([]);
      setCatalogue(null);
      return;
    }

    let active = true;

    async function loadRegionLayers() {
      try {
        setLayersLoading(true);
        setLayerError("");
        setLayers([]);
        setCatalogue(null);

        const data = await getRegionLayers(selectedRegion);

        if (!active) return;

        setCatalogue(data);

        setLayers(
          data.layers.map((layer) => ({
            ...layer,
            enabled: false,
          }))
        );
      } catch (error) {
        if (!active) return;

        setLayerError(
          error instanceof Error
            ? error.message
            : "Unable to load the layer catalogue."
        );
      } finally {
        if (active) {
          setLayersLoading(false);
        }
      }
    }

    loadRegionLayers();

    return () => {
      active = false;
    };
  }, [selectedRegion]);

  // Toggle layer selection
  function toggleLayer(id: string) {
    setLayers((current) =>
      current.map((layer) =>
        layer.layer_id === id
          ? { ...layer, enabled: !layer.enabled }
          : layer
      )
    );
  }

  // Change selected region
  function handleRegionChange(regionId: string) {
    setSelectedRegion(regionId);
    setMessage("");
    setRouteResult(null);
    setLayerError("");
    setMapCoordinate("");
    setStart("");
    setDestination("");
    setNextMapSelection("start");

    setBackendStatus({
      type: "idle",
      message: "Region changed. Ready for a new route request.",
    });
  }

  // Handle coordinate selection from map
  function handleMapCoordinateSelect(coordinate: string) {
    if (routeRequestInFlight.current) return;

    setMapCoordinate(coordinate);
    setRouteResult(null);

    if (nextMapSelection === "start") {
      setStart(coordinate);
      setNextMapSelection("destination");
      setMessage(
        "Starting point selected. Now click the map to select your destination."
      );
    } else {
      setDestination(coordinate);
      setNextMapSelection("start");
      setMessage(
        "Destination selected. Your coordinates are ready for validation."
      );
    }
  }

  // Reset map view and selection
  function resetMapView() {
    setMapResetSignal((current) => current + 1);
    setMapCoordinate("");
    setNextMapSelection("start");
    setMessage(
      "Map selection reset. Click the map to select a starting point."
    );
  }

  // Prepare and submit route request
  async function prepareRoute() {
    if (routeRequestInFlight.current) return;

    setRouteResult(null);
    setMessage("");

    // Check that both fields are filled
    if (!start.trim() || !destination.trim()) {
      setMessage(
        "Enter both starting and destination coordinates."
      );
      return;
    }

    // Validate coordinate format and ranges
    const startPoint = parseMarsCoordinate(start);
    const destinationPoint = parseMarsCoordinate(destination);

    if (!startPoint) {
      setMessage(
        "Invalid starting coordinates. Use latitude (-90 to 90), longitude (-180 to 180)."
      );
      return;
    }

    if (!destinationPoint) {
      setMessage(
        "Invalid destination coordinates. Use latitude (-90 to 90), longitude (-180 to 180)."
      );
      return;
    }

    // Prevent identical start and destination coordinates
    if (
      startPoint.latitude === destinationPoint.latitude &&
      startPoint.longitude === destinationPoint.longitude
    ) {
      setMessage(
        "Starting point and destination cannot be identical. Please choose a different destination."
      );
      return;
    }

    // Check selected region
    if (!selectedRegion) {
      setMessage("Please select a valid Mars region.");
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
      routing_profile: "safe",
    };

    // Lock before starting the asynchronous request.
    routeRequestInFlight.current = true;
    setIsLoading(true);

    setBackendStatus({
      type: "loading",
      message: "Sending route request to AresPath backend...",
    });

    try {
      const result = await calculateRoute(request);

      setRouteResult(result);

      setBackendStatus({
        type: "success",
        message: "Route calculated successfully.",
      });
    } catch (error) {
      setBackendStatus({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Unable to calculate route. Please try again.",
      });
    } finally {
      routeRequestInFlight.current = false;
      setIsLoading(false);
    }
  }

  const activeLayers = layers.filter((layer) => layer.enabled).length;

  return (
    <main className="app-shell">
      {/* TOP NAVIGATION */}
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

          {/* REGION SELECTOR */}
          <div className="section-label">ACTIVE REGION</div>

          <div className="region-card">
            <div className="region-icon">⌖</div>

            <div style={{ width: "100%" }}>
              <strong>SELECT MARS REGION</strong>

              <select
                value={selectedRegion}
                onChange={(event) =>
                  handleRegionChange(event.target.value)
                }
                disabled={regionsLoading || regions.length === 0}
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
                {regionsLoading && (
                  <option value="">Loading regions...</option>
                )}

                {!regionsLoading && regions.length === 0 && (
                  <option value="">No regions available</option>
                )}

                {regions.map((region) => (
                  <option
                    key={region.region_id}
                    value={region.region_id}
                  >
                    {region.display_name}
                  </option>
                ))}
              </select>

              <span
                style={{
                  display: "block",
                  marginTop: "8px",
                  fontSize: "11px",
                }}
              >
                Region ID: {selectedRegion || "Not selected"}
              </span>

              {regionsLoading && (
                <p style={{ fontSize: "12px", marginTop: "8px" }}>
                  Fetching available Mars regions...
                </p>
              )}

              {regionError && (
                <p
                  style={{
                    color: "#e47777",
                    fontSize: "12px",
                    marginTop: "8px",
                  }}
                >
                  {regionError}
                </p>
              )}
            </div>
          </div>

          {/* VERIFIED LAYER CATALOGUE */}
          <div className="catalogue-panel">
            <button
              type="button"
              onClick={() =>
                setCatalogueExpanded((current) => !current)
              }
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
                  <strong>
                    {layersLoading
                      ? "..."
                      : catalogue?.total_count ?? 0}
                  </strong>
                </div>

                {layersLoading && (
                  <p style={{ fontSize: "12px" }}>
                    Loading verified layers...
                  </p>
                )}

                {layerError && (
                  <div
                    style={{
                      padding: "12px",
                      border: "1px solid #e47777",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                  >
                    <strong>Catalogue unavailable</strong>
                    <p style={{ marginTop: "6px" }}>
                      {layerError}
                    </p>
                  </div>
                )}

                {!layersLoading &&
                  !layerError &&
                  layers.length === 0 && (
                    <div
                      style={{
                        padding: "14px",
                        border: "1px solid #46515d",
                        borderRadius: "8px",
                        background: "#17212b",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "20px",
                          marginBottom: "8px",
                        }}
                      >
                        ◈
                      </div>

                      <strong>
                        No verified terrain layers yet
                      </strong>

                      <p
                        style={{
                          fontSize: "12px",
                          marginTop: "8px",
                        }}
                      >
                        {catalogue?.notice ||
                          "No verified datasets have been ingested for this region."}
                      </p>
                    </div>
                  )}

                {!layersLoading && layers.length > 0 && (
                  <div
                    style={{
                      padding: "12px",
                      border: "1px solid #46515d",
                      borderRadius: "8px",
                      background: "#17212b",
                    }}
                  >
                    <strong>
                      {catalogue?.verified_layers_available
                        ? "Verified datasets available"
                        : "Catalogue datasets"}
                    </strong>

                    <p
                      style={{
                        fontSize: "12px",
                        marginTop: "6px",
                      }}
                    >
                      Select a layer below to mark it for display.
                      Map rendering integration is still pending.
                    </p>
                  </div>
                )}

                <div
                  style={{
                    marginTop: "12px",
                    fontSize: "11px",
                  }}
                >
                  SELECTED REGION: {selectedRegion || "NONE"}
                </div>
              </div>
            )}
          </div>

          {/* DYNAMIC DATA OVERLAYS */}
          <div className="section-label layer-section-label">
            DATA OVERLAYS
            <span>{activeLayers} SELECTED</span>
          </div>

          <div className="layer-list">
            {layers.map((layer) => (
              <button
                key={layer.layer_id}
                type="button"
                className={`layer-item ${
                  layer.enabled ? "active" : ""
                }`}
                onClick={() => toggleLayer(layer.layer_id)}
                disabled={!layer.is_verified}
                title={
                  !layer.is_verified
                    ? "This layer is not verified."
                    : "Toggle layer selection"
                }
              >
                <span
                  className="layer-color"
                  style={{
                    backgroundColor: getLayerColor(layer.layer_type),
                  }}
                />

                <span className="layer-info">
                  <strong>{layer.display_name}</strong>
                  <small>
                    {layer.layer_type.toUpperCase()}
                    {layer.resolution_m_per_px
                      ? ` · ${layer.resolution_m_per_px} m/px`
                      : ""}
                  </small>
                </span>

                <span className="layer-toggle">
                  {layer.enabled ? "ON" : "OFF"}
                </span>
              </button>
            ))}

            {!layersLoading &&
              !layerError &&
              layers.length === 0 && (
                <p
                  style={{
                    fontSize: "12px",
                    padding: "8px 0",
                    opacity: 0.7,
                  }}
                >
                  No layers to display for this region.
                </p>
              )}
          </div>

          <div className="panel-note">
            <span className="note-icon">ⓘ</span>

            <p>
              Only backend-catalogued datasets are displayed here.
              Layer rendering will be enabled after scientific map
              integration.
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
              <span className="eyebrow">
                PLANETARY VIEWER / 01
              </span>
              <h1>Mars surface explorer</h1>
            </div>

            <div className="map-toolbar-right">
              <span className="view-chip">
                <span className="status-dot" />
                MAP WORKSPACE
              </span>

              <button
                className="icon-button"
                type="button"
                title="Reset map view"
                onClick={resetMapView}
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
              DISPLAY: INTERACTIVE COORDINATE GRID · NO SCIENTIFIC TERRAIN DATA
            </div>

            <MarsMap
              selectedRegion={selectedRegion}
              resetSignal={mapResetSignal}
              onCoordinateSelect={handleMapCoordinateSelect}
            />

            {/* NEXT MAP SELECTION INDICATOR */}
            <div
              style={{
                position: "absolute",
                top: "52px",
                right: "16px",
                zIndex: 5,
                padding: "10px 14px",
                background: "#17212b",
                border: "1px solid #526779",
                borderRadius: "8px",
                color: "#ffffff",
                fontSize: "12px",
              }}
            >
              NEXT MAP CLICK:{" "}
              <strong>
                {nextMapSelection === "start"
                  ? "STARTING POINT"
                  : "DESTINATION"}
              </strong>
            </div>

            {mapCoordinate && (
              <div
                style={{
                  position: "absolute",
                  top: "52px",
                  left: "16px",
                  zIndex: 5,
                  padding: "10px 14px",
                  background: "#17212b",
                  border: "1px solid #526779",
                  borderRadius: "8px",
                  color: "#ffffff",
                  fontSize: "12px",
                }}
              >
                LAST SELECTED: {mapCoordinate}
              </div>
            )}

            <div className="map-center-message">
              <span className="preview-tag">
                INTERACTIVE PREVIEW
              </span>

              <strong>
                Mars coordinate workspace
              </strong>

              <span>
                Click once to select your starting point, then click
                again to select your destination. You can also enter
                coordinates manually in the walk planner.
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
              <strong>Preview coordinates only</strong>
            </div>

            <div>
              <span>ROUTE ENGINE</span>
              <strong>
                {routeResult
                  ? "Route response received"
                  : "Awaiting route request"}
              </strong>
            </div>
          </div>
        </section>

        {/* RIGHT PANEL: WALK PLANNER */}
        <aside className="panel right-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">
                NAVIGATION TOOLS
              </span>
              <h2>Walk planner</h2>
            </div>

            <span className="heading-icon">⌁</span>
          </div>

          <div className="planner-intro">
            Enter Mars coordinates to prepare a surface route
            request. Use latitude, longitude in degrees. You can
            click the map to select your starting point and destination.
          </div>

          <div className="route-form" aria-busy={isLoading}>
            <label htmlFor="start-point">
              STARTING POINT
            </label>

            <div className="field-wrap">
              <span className="field-marker start-marker" />

              <input
                id="start-point"
                value={start}
                onChange={(event) => {
                  setStart(event.target.value);
                  setRouteResult(null);
                }}
                placeholder="Example: 18.30, 77.20"
                disabled={isLoading}
              />
            </div>

            <div className="route-connector">
              <span />
            </div>

            <label htmlFor="destination-point">
              DESTINATION
            </label>

            <div className="field-wrap">
              <span className="field-marker end-marker" />

              <input
                id="destination-point"
                value={destination}
                onChange={(event) => {
                  setDestination(event.target.value);
                  setRouteResult(null);
                }}
                placeholder="Example: 18.50, 77.40"
                disabled={isLoading}
              />
            </div>

            <button
              type="button"
              className="primary-button"
              onClick={prepareRoute}
              disabled={isLoading || !selectedRegion}
            >
              {isLoading
                ? "CALCULATING ROUTE..."
                : "CALCULATE ROUTE"}
              <span>→</span>
            </button>

            {/* DEDICATED BACKEND STATUS PANEL */}
            <div
              className={`backend-status backend-status-${backendStatus.type}`}
              role="status"
              aria-live="polite"
            >
              <div className="backend-status-heading">
                <span className="backend-status-indicator" />

                <strong>
                  {backendStatus.type === "loading"
                    ? "BACKEND REQUEST IN PROGRESS"
                    : backendStatus.type === "success"
                      ? "REQUEST COMPLETED"
                      : backendStatus.type === "error"
                        ? "BACKEND REQUEST FAILED"
                        : "BACKEND STATUS"}
                </strong>
              </div>

              <p>{backendStatus.message}</p>
            </div>

            {/* EXISTING MAP AND VALIDATION MESSAGES */}
            {message && (
              <div className="form-message" role="status">
                {message}
              </div>
            )}

            {/* IMPROVEMENT 5: COMPLETE ROUTE ANALYSIS */}
            {routeResult && (
              <section className="route-details">
                <div className="route-details-header">
                  <h3>ROUTE ANALYSIS</h3>
                  <span className="route-success-badge">
                    SUCCESS
                  </span>
                </div>

                {/* DISTANCE */}
                <div className="route-detail-card">
                  <span className="route-detail-label">
                    TOTAL ROUTE DISTANCE
                  </span>

                  <div className="route-distance">
                    {(routeResult.distance_m / 1000).toFixed(2)}
                    <span> km</span>
                  </div>

                  <p>
                    {routeResult.distance_m.toLocaleString()} metres
                  </p>
                </div>

                {/* TRAVERSAL COST */}
                <div className="route-detail-card">
                  <span className="route-detail-label">
                    ESTIMATED TRAVERSAL COST
                  </span>

                  <p className="unavailable-value">
                    Not provided by backend
                  </p>

                  <small>
                    Terrain-based movement cost is not yet available
                    in the current API response.
                  </small>
                </div>

                {/* ROUTE METADATA */}
                <div className="route-metadata">
                  <div>
                    <span>Route ID</span>
                    <strong>{routeResult.route_id}</strong>
                  </div>

                  <div>
                    <span>Algorithm</span>
                    <strong>
                      {routeResult.algorithm.toUpperCase()}
                    </strong>
                  </div>

                  <div>
                    <span>Region</span>
                    <strong>{routeResult.region_id}</strong>
                  </div>

                  <div>
                    <span>Route status</span>
                    <strong>{routeResult.status.toUpperCase()}</strong>
                  </div>
                </div>

                {/* WAYPOINT INFORMATION */}
                <div className="route-waypoints">
                  <div className="route-section-heading">
                    <h4>WAYPOINT INFORMATION</h4>

                    <span>
                      {routeResult.route_geometry.points.length} points
                    </span>
                  </div>

                  {routeResult.route_geometry.points.length > 0 ? (
                    <div className="waypoint-list">
                      {routeResult.route_geometry.points.map(
                        (point, index) => {
                          const totalPoints =
                            routeResult.route_geometry.points.length;

                          const pointLabel =
                            index === 0
                              ? "START"
                              : index === totalPoints - 1
                                ? "DESTINATION"
                                : `WAYPOINT ${index + 1}`;

                          return (
                            <div
                              className="waypoint-row"
                              key={`${index}-${point.x}-${point.y}`}
                            >
                              <span className="waypoint-number">
                                {index + 1}
                              </span>

                              <div>
                                <strong>{pointLabel}</strong>

                                <p>
                                  X: {point.x.toFixed(2)} m | Y:{" "}
                                  {point.y.toFixed(2)} m
                                </p>
                              </div>
                            </div>
                          );
                        }
                      )}
                    </div>
                  ) : (
                    <p>
                      No waypoint coordinates returned by backend.
                    </p>
                  )}

                  <small>
                    Coordinates use the AresPath display coordinate
                    system, not latitude/longitude.
                  </small>
                </div>

                {/* TERRAIN SUMMARY */}
                <div className="route-terrain">
                  <h4>TERRAIN SUMMARY</h4>

                  <div className="route-metadata">
                    <div>
                      <span>Minimum elevation</span>
                      <strong>
                        {routeResult.terrain_summary.min_elevation_m != null
                          ? `${routeResult.terrain_summary.min_elevation_m} m`
                          : "Unavailable"}
                      </strong>
                    </div>

                    <div>
                      <span>Maximum elevation</span>
                      <strong>
                        {routeResult.terrain_summary.max_elevation_m != null
                          ? `${routeResult.terrain_summary.max_elevation_m} m`
                          : "Unavailable"}
                      </strong>
                    </div>

                    <div>
                      <span>Maximum slope</span>
                      <strong>
                        {routeResult.terrain_summary.max_slope_deg != null
                          ? `${routeResult.terrain_summary.max_slope_deg}°`
                          : "Unavailable"}
                      </strong>
                    </div>

                    <div>
                      <span>Hazard count</span>
                      <strong>
                        {routeResult.terrain_summary.hazard_count}
                      </strong>
                    </div>
                  </div>

                  <span className="route-detail-label">
                    SURFACE TYPES
                  </span>

                  <p>
                    {routeResult.terrain_summary.surface_types.length > 0
                      ? routeResult.terrain_summary.surface_types.join(", ")
                      : "No surface types available"}
                  </p>
                </div>

                {/* WARNINGS */}
                {routeResult.warnings.length > 0 && (
                  <div className="route-warnings">
                    <h4>ROUTE WARNINGS</h4>

                    {routeResult.warnings.map((warning, index) => (
                      <p key={index}>⚠ {warning}</p>
                    ))}
                  </div>
                )}

                {/* DATA SOURCES */}
                <div className="route-data-sources">
                  <h4>DATA SOURCES</h4>

                  {routeResult.data_sources.length > 0 ? (
                    <ul>
                      {routeResult.data_sources.map((source, index) => (
                        <li key={index}>{source}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>No data sources listed.</p>
                  )}
                </div>
              </section>
            )}
          </div>

          <div className="section-divider" />

          <div className="section-label">
            ROUTE PARAMETERS
          </div>

          <div className="parameter-row">
            <span>Algorithm</span>
            <strong>
              {routeResult
                ? routeResult.algorithm.toUpperCase()
                : "Backend selected"}
            </strong>
          </div>

          <div className="parameter-row">
            <span>Routing profile</span>
            <strong>Safe</strong>
          </div>

          <div className="parameter-row">
            <span>Terrain cost</span>
            <strong>Not configured</strong>
          </div>

          <div className="route-warning">
            <span>⚠</span>

            <p>
              AresPath is a research and visualization prototype.
              Calculated routes are not certified for astronaut
              navigation or mission safety.
            </p>
          </div>

          <div className="planner-footer">
            <span className="eyebrow">
              ARESPATH / MVP BUILD
            </span>

            <strong>Explore with evidence.</strong>
          </div>
        </aside>
      </div>

      {/* FOOTER */}
      <footer className="app-footer">
        <span>ARESPATH © 2026</span>
        <span>RESEARCH & VISUALIZATION PROTOTYPE</span>
        <span>
          NOT CERTIFIED FOR ASTRONAUT NAVIGATION
        </span>
      </footer>
    </main>
  );
}