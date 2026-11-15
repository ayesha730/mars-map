export interface MarsCoordinate {
  latitude: number;
  longitude: number;
}

export interface CoordinateReference {
  body: "Mars";
  latitude_type: "planetocentric";
  longitude_direction: "positive_east";
  longitude_domain: "-180_to_180";
  angular_unit: "degrees";
}

export type RoutingProfile = "safe" | "fast" | "science";

export interface RouteRequest {
  region_id: string;
  start: MarsCoordinate;
  destination: MarsCoordinate;
  coordinate_reference: CoordinateReference;
  routing_profile: RoutingProfile;
}

export interface RoutePoint {
  x: number;
  y: number;
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
  route_geometry: {
    coordinate_space: "arespath_display_v1";
    points: RoutePoint[];
  };
  terrain_summary: TerrainSummary;
  warnings: string[];
  data_sources: string[];
}

export interface ApiErrorResponse {
  status: "error";
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
  request_id?: string | null;
}

export interface HealthResponse {
  status: string;
  project: string;
  version: string;
  body: string;
  datum: string;
}

export interface DatasetProvenance {
  name: string;
  agency: string;
  instrument?: string | null;
  mission?: string | null;
  resolution_m_per_px?: number | null;
  coverage?: string | null;
  reference_url?: string | null;
  is_synthetic: boolean;
  synthetic_description?: string | null;
}

export interface MarsRegion {
  region_id: string;
  display_name: string;
  description?: string | null;
  source_crs: CoordinateReference;
  display_coordinate_space: "arespath_display_v1";
  display_projection: {
    projection_name?: string | null;
    proj4_string?: string | null;
    wkt2_string?: string | null;
    datum: string;
    semi_major_axis_m: number;
    is_spherical: boolean;
  };
  display_origin: {
    description: string;
    latitude_deg?: number | null;
    longitude_deg?: number | null;
    source?: string | null;
  };
  x_axis: "East, metres";
  y_axis: "North, metres";
  transformation: {
    method: string;
    parameters?: Record<string, unknown> | null;
    notes?: string | null;
  };
  datasets: DatasetProvenance[];
  routing_available: boolean;
  routing_unavailable_reason?: string | null;
}

export interface MarsLayer {
  layer_id: string;
  region_id: string;
  layer_type: "dem" | "orthoimage" | "slope" | "hazard" | "geologic" | "custom";
  display_name: string;
  description?: string | null;
  is_verified: boolean;
  is_synthetic: boolean;
  resolution_m_per_px?: number | null;
  coverage?: string | null;
  data_source?: string | null;
  reference_url?: string | null;
}

export interface LayersResponse {
  region_id: string;
  verified_layers_available: boolean;
  total_count: number;
  layers: MarsLayer[];
  notice?: string | null;
}