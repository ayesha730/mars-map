import type {
  RouteRequest,
  RouteResponse,
  RegionSummary,
  LayerCatalogueResponse,
  ApiErrorResponse,
  RoutePoint,
} from "@/types/api";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export const MARS_SPHERE_RADIUS_M = 3396190.0;
export const JEZERO_STANDARD_PARALLEL_DEG = 18.4663;

/**
 * Converts an AresPath display point (X, Y in metres) to geographic [longitude, latitude] in degrees.
 * Display projection is Equirectangular Mars 2000 Sphere with standard parallel 18.4663°N.
 */
export function displayPointToLonLat(point: RoutePoint): [number, number] {
  const stdParallelRad = (JEZERO_STANDARD_PARALLEL_DEG * Math.PI) / 180;
  const cosStdParallel = Math.cos(stdParallelRad);

  const lonRad = point.x / (MARS_SPHERE_RADIUS_M * cosStdParallel);
  const latRad = point.y / MARS_SPHERE_RADIUS_M;

  const lonDeg = (lonRad * 180) / Math.PI;
  const latDeg = (latRad * 180) / Math.PI;

  return [lonDeg, latDeg];
}

/**
 * Converts geographic [longitude, latitude] in degrees to AresPath display point (X, Y in metres).
 */
export function lonLatToDisplayPoint(lonDeg: number, latDeg: number): RoutePoint {
  const stdParallelRad = (JEZERO_STANDARD_PARALLEL_DEG * Math.PI) / 180;
  const cosStdParallel = Math.cos(stdParallelRad);

  const lonRad = (lonDeg * Math.PI) / 180;
  const latRad = (latDeg * Math.PI) / 180;

  const x = MARS_SPHERE_RADIUS_M * cosStdParallel * lonRad;
  const y = MARS_SPHERE_RADIUS_M * latRad;

  return { x, y };
}

/**
 * Sends a route request to the FastAPI backend.
 */
export async function calculateRoute(
  request: RouteRequest,
): Promise<RouteResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/routes`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    body: JSON.stringify(request),
  });

  const data: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const errorData = data as ApiErrorResponse | null;
    throw new Error(
      errorData?.error?.message ||
        `Route request failed with status ${response.status}`,
    );
  }

  return data as RouteResponse;
}

/**
 * Checks backend connectivity.
 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
      method: "GET",
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Fetches available regions from the backend.
 * Handles both direct array of regions or object containing `regions` key.
 */
export async function fetchRegions(): Promise<RegionSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/regions`, {
    method: "GET",
    headers: {
      "Accept": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch regions (${response.status})`);
  }

  const data = await response.json();
  if (Array.isArray(data)) {
    return data as RegionSummary[];
  }
  if (data && Array.isArray(data.regions)) {
    return data.regions as RegionSummary[];
  }
  return [];
}

/**
 * Fetches the layer catalogue for a specified region.
 */
export async function fetchLayers(regionId: string): Promise<LayerCatalogueResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/layers?region_id=${encodeURIComponent(regionId)}`, {
    method: "GET",
    headers: {
      "Accept": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch layer catalogue (${response.status})`);
  }

  return (await response.json()) as LayerCatalogueResponse;
}

/**
 * Generates the preview URL for a raster layer.
 */
export function getRasterPreviewUrl(
  layerId: string,
  bounds: {
    min_lon: number;
    min_lat: number;
    max_lon: number;
    max_lat: number;
    max_dimension?: number;
  },
): string {
  const params = new URLSearchParams({
    min_lon: bounds.min_lon.toString(),
    min_lat: bounds.min_lat.toString(),
    max_lon: bounds.max_lon.toString(),
    max_lat: bounds.max_lat.toString(),
    max_dimension: (bounds.max_dimension || 1024).toString(),
  });
  return `${API_BASE_URL}/api/v1/layers/${encodeURIComponent(layerId)}/preview?${params.toString()}`;
}

export const getRegions = fetchRegions;
export const getRegionLayers = fetchLayers;
