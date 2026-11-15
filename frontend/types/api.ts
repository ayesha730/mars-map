// Mars coordinate supplied to the AresPath backend
export interface MarsPoint {
  latitude: number;
  longitude: number;
}

export type MarsCoordinate = MarsPoint;

// Coordinate conventions must be explicit
export interface CoordinateReference {
  body: "Mars";
  latitude_type: "planetocentric" | "planetographic";
  longitude_direction: "positive_east" | "positive_west";
  longitude_domain: "-180_to_180" | "0_to_360";
  angular_unit: "degrees";
}

// Request sent to POST /api/v1/routes
export interface RouteRequest {
  region_id: string;
  start: MarsPoint;
  destination: MarsPoint;
  coordinate_reference: CoordinateReference;
  routing_profile?: "demonstration" | "safe" | "fast" | "science" | string;
}

// Route points use AresPath's documented display coordinate space (metres)
export interface RoutePoint {
  x: number;
  y: number;
}

// Successful route response
export interface RouteResponse {
  status: "success";
  route_id: string;
  region_id: string;
  algorithm: string;
  distance_m: number;

  route_geometry: {
    coordinate_space: "arespath_display_v1";
    points: RoutePoint[];
  };

  terrain_summary?: {
    metric?: string;
    value?: number;
    interpretation?: string;
  };

  warnings: string[];
  data_sources: string[];
}

// Region types from GET /api/v1/regions
export interface RegionSummary {
  region_id: string;
  display_name: string;
  description?: string;
  routing_available: boolean;
  routing_unavailable_reason?: string | null;
  center_lat_deg?: number;
  center_lon_deg?: number;
  min_lat_deg?: number;
  max_lat_deg?: number;
  min_lon_deg?: number;
  max_lon_deg?: number;
  display_origin?: {
    latitude_deg?: number | null;
    longitude_deg?: number | null;
  };
}

export interface RegionListResponse {
  regions: RegionSummary[];
}

// Layer types from GET /api/v1/layers?region_id=...
export interface LayerCatalogueEntry {
  layer_id: string;
  region_id: string;
  layer_type: "elevation_dem" | "orthoimage" | string;
  display_name: string;
  description: string;
  is_verified: boolean;
  is_synthetic: boolean;
  resolution_m_per_px?: number | null;
  coverage?: string | null;
  agency?: string | null;
  instrument?: string | null;
  reference_url?: string | null;
  preview_supported: boolean;
}

export interface LayerCatalogueResponse {
  region_id: string;
  verified_layers_available: boolean;
  layers: LayerCatalogueEntry[];
  notice?: string | null;
}

export type MarsRegion = RegionSummary;
export type LayersResponse = LayerCatalogueResponse;

export interface HealthResponse {
  status: string;
  project?: string;
  version?: string;
  body?: string;
  datum?: string;
}

// Error response from the backend
export interface ApiErrorResponse {
  status: "error";
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown> | Array<unknown>;
  };
  request_id: string;
}
