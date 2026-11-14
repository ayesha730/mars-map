// Mars coordinate supplied to the AresPath backend
export interface MarsCoordinate {
  latitude_deg: number;
  longitude_deg: number;
}

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
  start: MarsCoordinate;
  destination: MarsCoordinate;
  coordinate_reference: CoordinateReference;
  routing_profile: "demonstration";
}

// Route points use AresPath's documented display coordinate space
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

  terrain_summary: {
    metric: string;
    value: number;
    interpretation: string;
  };

  warnings: string[];
  data_sources: string[];
}

// Error response from the backend
export interface ApiErrorResponse {
  status: "error";
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  request_id: string;
}