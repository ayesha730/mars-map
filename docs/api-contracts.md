# AresPath API Contracts — v1

> **Project**: AresPath — NASA Space Apps Challenge 2026  
> **API version**: v1  
> **Base URL**: `/api/v1`  
> **Last updated**: 2026-11-14

---

## Table of Contents

1. [Coordinate Convention](#1-coordinate-convention)
2. [Display Coordinate Space](#2-display-coordinate-space)
3. [Standard Error Envelope](#3-standard-error-envelope)
4. [Endpoints](#4-endpoints)
   - [GET /health](#41-get-health)
   - [POST /routes](#42-post-routes)
   - [GET /regions](#43-get-regions)
   - [GET /regions/{region_id}](#44-get-regionsregion_id)
   - [GET /layers](#45-get-layers)
   - [GET /layers/{layer_id}/metadata](#46-get-layerslayer_idmetadata)
5. [TypeScript Type Definitions](#5-typescript-type-definitions)
6. [Integration Blockers](#6-integration-blockers)

---

## 1. Coordinate Convention

All Mars surface coordinates in AresPath use the following convention — **always**:

| Field | Value |
|---|---|
| `body` | `"Mars"` |
| `latitude_type` | `"planetocentric"` |
| `longitude_direction` | `"positive_east"` |
| `longitude_domain` | `"-180_to_180"` |
| `angular_unit` | `"degrees"` |
| `datum` | `IAU:2015:49900` (Mean Volumetric Sphere, R = 3 396 190 m) |

The `coordinate_reference` object in every route request must match these values exactly. The API will return `VALIDATION_ERROR` (HTTP 422) if any field differs.

---

## 2. Display Coordinate Space

Route geometry is returned in the `arespath_display_v1` coordinate space:

| Property | Value |
|---|---|
| `coordinate_space` | `"arespath_display_v1"` |
| X-axis | East, **metres** from region display origin |
| Y-axis | North, **metres** from region display origin |
| Projection | Region-specific (see `/api/v1/regions/{region_id}`) |
| Origin | Region-specific (see `display_origin` in region metadata) |

> **Note**: The numeric projection parameters and origin coordinates are populated from verified dataset metadata only. Fields are `null` until a DEM dataset is integrated — see [Integration Blockers](#6-integration-blockers).

---

## 3. Standard Error Envelope

**All errors** — validation, routing, server — return the same JSON shape:

```json
{
  "status": "error",
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description.",
    "details": { }
  },
  "request_id": "uuid-v4"
}
```

| HTTP Status | `error.code` | Meaning |
|---|---|---|
| 422 | `VALIDATION_ERROR` | Missing/invalid request field |
| 404 | `REGION_NOT_FOUND` | `region_id` not in registry |
| 503 | `ROUTING_DATA_UNAVAILABLE` | No verified DEM/routing service wired in |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected server fault |

---

## 4. Endpoints

### 4.1 GET /health

**Response 200**

```json
{
  "status": "OK",
  "project": "AresPath",
  "version": "0.1.0",
  "body": "Mars",
  "datum": "IAU:2015:49900"
}
```

---

### 4.2 POST /routes

Compute a surface traversal route between two Mars coordinates.

#### Request

```json
{
  "region_id": "jezero_crater",
  "start": {
    "latitude": 18.4,
    "longitude": 77.5
  },
  "destination": {
    "latitude": 18.6,
    "longitude": 77.9
  },
  "coordinate_reference": {
    "body": "Mars",
    "latitude_type": "planetocentric",
    "longitude_direction": "positive_east",
    "longitude_domain": "-180_to_180",
    "angular_unit": "degrees"
  },
  "routing_profile": "safe"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `region_id` | `string` | ✅ | Must be a registered region |
| `start.latitude` | `float` | ✅ | Planetocentric degrees, −90..90 |
| `start.longitude` | `float` | ✅ | Positive-East degrees, −180..180 |
| `destination.latitude` | `float` | ✅ | Same range |
| `destination.longitude` | `float` | ✅ | Same range |
| `coordinate_reference` | object | optional | Defaults to confirmed Mars convention |
| `routing_profile` | `"safe"` \| `"fast"` \| `"science"` | optional | Default `"safe"` |

#### Response 200 — Success (future state, pending DEM integration)

```json
{
  "status": "success",
  "route_id": "uuid-v4",
  "region_id": "jezero_crater",
  "algorithm": "a_star",
  "distance_m": 44320.5,
  "route_geometry": {
    "coordinate_space": "arespath_display_v1",
    "points": [
      { "x": 0.0, "y": 0.0 },
      { "x": 1200.5, "y": 850.3 }
    ]
  },
  "terrain_summary": {
    "min_elevation_m": -2500.0,
    "max_elevation_m": -2200.0,
    "max_slope_deg": 12.3,
    "hazard_count": 1,
    "surface_types": ["regolith", "delta_fan"]
  },
  "warnings": ["Slope exceeds 10° at waypoint 14"],
  "data_sources": ["MRO_CTX_DEM_v1", "HiRISE_Ortho_ESP_046060_1985"]
}
```

#### Response 503 — ROUTING_DATA_UNAVAILABLE (current state)

```json
{
  "status": "error",
  "error": {
    "code": "ROUTING_DATA_UNAVAILABLE",
    "message": "Routing is not available for region 'jezero_crater'. ...",
    "details": {
      "region_id": "jezero_crater",
      "routing_profile": "safe",
      "great_circle_distance_m": 42318.44,
      "distance_method": "haversine_spherical_approximation_IAU2015",
      "distance_disclaimer": "Great-circle distance is a spherical approximation using MARS_IAU2015_SPHERE_RADIUS_M=3396190 m. It does NOT account for terrain, obstacles, or slope. It is not a navigable route.",
      "integration_status": "pending"
    }
  },
  "request_id": "uuid-v4"
}
```

> **Frontend guidance**: Check `error.code === "ROUTING_DATA_UNAVAILABLE"` and display `error.details.great_circle_distance_m` as an informational straight-line estimate, not a navigable route. The `distance_disclaimer` text should be shown to the user.

#### Response 404 — Region not found

```json
{
  "status": "error",
  "error": {
    "code": "REGION_NOT_FOUND",
    "message": "Region 'atlantis' is not recognised.",
    "details": {
      "region_id": "atlantis",
      "supported_regions": ["jezero_crater", "gale_crater"]
    }
  },
  "request_id": "uuid-v4"
}
```

---

### 4.3 GET /regions

Returns a list of all registered Mars surface regions with full metadata.

**Response 200** — Array of [RegionMetadata](#44-get-regionsregion_id) objects.

---

### 4.4 GET /regions/{region_id}

Returns full metadata for a single region.

#### Response 200

```json
{
  "region_id": "jezero_crater",
  "display_name": "Jezero Crater",
  "description": "Ancient lake-delta system, landing site of Perseverance (~18.4°N, 77.7°E).",
  "source_crs": {
    "body": "Mars",
    "latitude_type": "planetocentric",
    "longitude_direction": "positive_east",
    "longitude_domain": "-180_to_180",
    "angular_unit": "degrees"
  },
  "display_coordinate_space": "arespath_display_v1",
  "display_projection": {
    "projection_name": null,
    "proj4_string": null,
    "wkt2_string": null,
    "datum": "IAU:2015:49900",
    "semi_major_axis_m": 3396190.0,
    "is_spherical": true
  },
  "display_origin": {
    "description": "Region-specific origin — to be defined from verified DEM dataset extent.",
    "latitude_deg": null,
    "longitude_deg": null,
    "source": null
  },
  "x_axis": "East, metres",
  "y_axis": "North, metres",
  "transformation": {
    "method": "Pending — awaiting verified DEM dataset integration",
    "parameters": null,
    "notes": "Transformation from Mars planetocentric lat/lon to the arespath_display_v1 local East-North frame will be defined once the HiRISE/CTX DEM PDS label is processed."
  },
  "datasets": [
    {
      "name": "Placeholder — no verified terrain dataset integrated",
      "agency": "N/A",
      "instrument": null,
      "mission": null,
      "resolution_m_per_px": null,
      "coverage": null,
      "reference_url": null,
      "is_synthetic": true,
      "synthetic_description": "Real data would be a CTX or HiRISE DEM from MRO, available via NASA PDS Geosciences Node."
    }
  ],
  "routing_available": false,
  "routing_unavailable_reason": "ROUTING_DATA_UNAVAILABLE"
}
```

**Null fields**: `projection_name`, `proj4_string`, `wkt2_string`, `display_origin.latitude_deg`, `display_origin.longitude_deg`, `transformation.parameters` are intentionally `null` until a verified dataset (CTX/HiRISE DEM) is integrated. **Do not invent these values.**

---

### 4.5 GET /layers

Returns the layer catalogue for a region. Accepts a required `region_id` query parameter.

**Request**: `GET /api/v1/layers?region_id=jezero_crater`

#### Response 200 — Empty catalogue (current state: no DEM integrated)

```json
{
  "region_id": "jezero_crater",
  "verified_layers_available": false,
  "total_count": 0,
  "layers": [],
  "notice": "No verified terrain layers are currently registered for this region. Layers will appear here once a verified Mars surface dataset (e.g. MRO HiRISE or CTX DEM from NASA PDS Geosciences Node) has been integrated and validated. Do not use this response to infer that the region has no terrain data — it means only that AresPath has not yet ingested a dataset for it."
}
```

#### Response 200 — Populated catalogue (future state, after DEM integration)

```json
{
  "region_id": "jezero_crater",
  "verified_layers_available": true,
  "total_count": 2,
  "layers": [
    {
      "layer_id": "jezero_ctx_dem_v1",
      "region_id": "jezero_crater",
      "layer_type": "dem",
      "display_name": "Jezero Crater CTX DEM",
      "description": "...",
      "is_verified": true,
      "is_synthetic": false,
      "resolution_m_per_px": 18.0,
      "coverage": "...",
      "data_source": "MRO_CTX_DEM_...",
      "reference_url": "https://pds-geosciences.wustl.edu/..."
    }
  ],
  "notice": null
}
```

**Frontend guidance**:
- When `verified_layers_available` is `false`, display `notice` to the user and render no layers.
- When `layers` is non-empty, every entry with `is_verified: true` is from a real NASA dataset. Entries with `is_synthetic: true` are placeholders — do not present them as real science data.

| Field | Type | Notes |
|---|---|---|
| `region_id` | `string` | Echoes the query parameter |
| `verified_layers_available` | `boolean` | `false` until DEM integrated |
| `total_count` | `integer` | Length of `layers` array |
| `layers` | `LayerCatalogueEntry[]` | Empty until DEM integrated |
| `notice` | `string \| null` | Present and non-null when no verified data |

#### Response 404 — Unknown region

```json
{
  "status": "error",
  "error": {
    "code": "REGION_NOT_FOUND",
    "message": "Region 'atlantis' is not recognised.",
    "details": { "region_id": "atlantis", "supported_regions": ["gale_crater", "jezero_crater"] }
  },
  "request_id": "uuid-v4"
}
```

#### Response 422 — Missing region_id

```json
{
  "status": "error",
  "error": { "code": "VALIDATION_ERROR", "message": "Request validation failed.", "details": [...] },
  "request_id": "uuid-v4"
}
```

---

### 4.6 GET /layers/{layer_id}/metadata

Returns full coordinate-frame and provenance metadata for a single layer.

**Request**: `GET /api/v1/layers/jezero_ctx_dem_v1/metadata`

#### Response 200 (future state, after DEM integration)

```json
{
  "layer_id": "jezero_ctx_dem_v1",
  "region_id": "jezero_crater",
  "layer_type": "dem",
  "display_name": "Jezero Crater CTX DEM",
  "description": "...",
  "is_verified": true,
  "is_synthetic": false,
  "dataset_provenance": {
    "name": "MRO CTX DEM — Jezero Crater",
    "agency": "NASA",
    "instrument": "CTX",
    "mission": "Mars Reconnaissance Orbiter",
    "resolution_m_per_px": 18.0,
    "coverage": "...",
    "reference_url": "https://pds-geosciences.wustl.edu/...",
    "is_synthetic": false,
    "synthetic_description": null
  },
  "coordinate_frame": {
    "coordinate_space": "arespath_display_v1",
    "source_crs": {
      "body": "Mars",
      "latitude_type": "planetocentric",
      "longitude_direction": "positive_east",
      "longitude_domain": "-180_to_180",
      "angular_unit": "degrees"
    },
    "x_axis": "East, metres",
    "y_axis": "North, metres",
    "projection_name": null,
    "proj4_string": null,
    "datum": "IAU:2015:49900",
    "semi_major_axis_m": 3396190.0,
    "origin_latitude_deg": null,
    "origin_longitude_deg": null,
    "transformation_method": null,
    "transformation_parameters": null
  },
  "availability_note": null
}
```

> **Important**: All `null` fields in `coordinate_frame` remain `null` until a verified dataset PDS label is processed. Never invent projection parameters.

#### Response 404 — Layer not registered

```json
{
  "status": "error",
  "error": {
    "code": "LAYER_NOT_FOUND",
    "message": "Layer 'nonexistent_layer_xyz' is not registered.",
    "details": { "layer_id": "nonexistent_layer_xyz", "registered_layers": [] }
  },
  "request_id": "uuid-v4"
}
```

---

## 5. TypeScript Type Definitions

```typescript
// ── Coordinate convention ──────────────────────────────────────────────────

export interface MarsCoordinateReference {
  body: "Mars";
  latitude_type: "planetocentric";
  longitude_direction: "positive_east";
  longitude_domain: "-180_to_180";
  angular_unit: "degrees";
}

export interface MarsPoint {
  latitude: number;   // planetocentric degrees, -90..90
  longitude: number;  // positive-east degrees, -180..180
}

export type RoutingProfile = "safe" | "fast" | "science";

// ── Route request ──────────────────────────────────────────────────────────

export interface RouteRequest {
  region_id: string;
  start: MarsPoint;
  destination: MarsPoint;
  coordinate_reference?: MarsCoordinateReference;
  routing_profile?: RoutingProfile;
}

// ── Route response (success) ───────────────────────────────────────────────

export interface DisplayPoint {
  x: number;  // East, metres from region origin
  y: number;  // North, metres from region origin
}

export interface RouteGeometry {
  coordinate_space: "arespath_display_v1";
  points: DisplayPoint[];
}

export interface TerrainSummary {
  min_elevation_m: number | null;
  max_elevation_m: number | null;
  max_slope_deg: number | null;
  hazard_count: number;
  surface_types: string[];
}

export interface RouteResponse {
  status: "success";
  route_id: string;
  region_id: string;
  algorithm: "a_star" | "dijkstra" | "unavailable";
  distance_m: number;
  route_geometry: RouteGeometry;
  terrain_summary: TerrainSummary;
  warnings: string[];
  data_sources: string[];
}

// ── Error envelope ─────────────────────────────────────────────────────────

export interface ErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

export interface ErrorResponse {
  status: "error";
  error: ErrorDetail;
  request_id: string | null;
}

// ── Region metadata ────────────────────────────────────────────────────────

export interface DatasetProvenance {
  name: string;
  agency: string;
  instrument: string | null;
  mission: string | null;
  resolution_m_per_px: number | null;
  coverage: string | null;
  reference_url: string | null;
  is_synthetic: boolean;
  synthetic_description: string | null;
}

export interface RegionMetadata {
  region_id: string;
  display_name: string;
  description: string | null;
  source_crs: MarsCoordinateReference;
  display_coordinate_space: "arespath_display_v1";
  display_projection: {
    projection_name: string | null;
    proj4_string: string | null;
    wkt2_string: string | null;
    datum: string;
    semi_major_axis_m: number;
    is_spherical: boolean;
  };
  display_origin: {
    description: string;
    latitude_deg: number | null;
    longitude_deg: number | null;
    source: string | null;
  };
  x_axis: string;
  y_axis: string;
  transformation: {
    method: string;
    parameters: Record<string, unknown> | null;
    notes: string | null;
  };
  datasets: DatasetProvenance[];
  routing_available: boolean;
  routing_unavailable_reason: string | null;
}

// ── Union response type (what POST /routes returns) ────────────────────────

export type RouteApiResponse = RouteResponse | ErrorResponse;

// ── Layer catalogue types ──────────────────────────────────────────────────

export type LayerType = "dem" | "orthoimage" | "slope" | "hazard" | "geologic" | "custom";

export interface LayerCoordinateFrame {
  coordinate_space: "arespath_display_v1";
  source_crs: MarsCoordinateReference;
  x_axis: "East, metres";
  y_axis: "North, metres";
  projection_name: string | null;
  proj4_string: string | null;
  datum: string;
  semi_major_axis_m: number;
  origin_latitude_deg: number | null;
  origin_longitude_deg: number | null;
  transformation_method: string | null;
  transformation_parameters: Record<string, unknown> | null;
}

export interface LayerCatalogueEntry {
  layer_id: string;
  region_id: string;
  layer_type: LayerType;
  display_name: string;
  description: string | null;
  is_verified: boolean;
  is_synthetic: boolean;
  resolution_m_per_px: number | null;
  coverage: string | null;
  data_source: string | null;
  reference_url: string | null;
}

export interface LayerCatalogueResponse {
  region_id: string;
  verified_layers_available: boolean;
  total_count: number;
  layers: LayerCatalogueEntry[];
  notice: string | null;
}

export interface LayerMetadata {
  layer_id: string;
  region_id: string;
  layer_type: LayerType;
  display_name: string;
  description: string | null;
  is_verified: boolean;
  is_synthetic: boolean;
  dataset_provenance: DatasetProvenance;
  coordinate_frame: LayerCoordinateFrame;
  availability_note: string | null;
}
```

---

## 6. Integration Blockers

The following are known blockers before the frontend can receive a successful route (`status: "success"`):

| # | Blocker | File to update | Notes |
|---|---|---|---|
| 1 | **Verified Mars terrain data** | `app/api/v1/endpoints/routes.py` → `_compute_route()` | Wire a CTX or HiRISE DEM. Source: NASA PDS Geosciences Node |
| 2 | **A\* path-finding service** | `app/api/v1/endpoints/routes.py` → `_compute_route()` | Build graph from DEM, implement A\* with slope/hazard cost function |
| 3 | **Projection parameters** | `app/api/v1/endpoints/regions.py` → `_REGIONS` | Extract `proj4_string`, `wkt2_string`, origin, and transformation params from DEM PDS label |
| 4 | **Layer catalogue population** | `app/api/v1/endpoints/layers.py` → `_LAYER_CATALOGUE` | Add `LayerCatalogueEntry` with `is_verified=True` for each ingested dataset |
| 5 | **Layer metadata population** | `app/api/v1/endpoints/layers.py` → `_LAYER_METADATA` | Add `LayerMetadata` with PDS-sourced projection, origin, and transformation parameters |
| 6 | **`routing_available = True`** | `app/api/v1/endpoints/routes.py` and `regions.py` | Flip flag after items 1–2 are verified in integration testing |

> **Frontend**: Until blocker #1 is resolved, `POST /routes` will always return HTTP 503 with `error.code = "ROUTING_DATA_UNAVAILABLE"`. The `error.details.great_circle_distance_m` field can be displayed as an informational straight-line estimate (not a navigable route).

> **Layer frontend**: Until blockers #4–5 are resolved, `GET /api/v1/layers` will return an empty catalogue with `verified_layers_available: false`. Display the `notice` field to the user instead of a layer list.
