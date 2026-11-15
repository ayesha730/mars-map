import type {
  RouteRequest,
  RouteResponse,
  ApiErrorResponse,
  HealthResponse,
  MarsRegion,
  LayersResponse,
} from "@/types/api";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

/**
 * Shared API response handler.
 */
async function handleResponse<T>(response: Response): Promise<T> {
  const data: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const errorData = data as ApiErrorResponse | null;

    throw new Error(
      errorData?.error?.message ||
        `API request failed with status ${response.status}`,
    );
  }

  return data as T;
}

/**
 * Check whether the backend is responding.
 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
      method: "GET",
      cache: "no-store",
    });

    if (!response.ok) return false;

    const data = (await response.json()) as HealthResponse;
    return data.status === "OK";
  } catch {
    return false;
  }
}

/**
 * Fetch all supported Mars regions.
 * Backend returns a direct array of RegionMetadata.
 */
export async function getRegions(): Promise<MarsRegion[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/regions`, {
    method: "GET",
    cache: "no-store",
  });

  return handleResponse<MarsRegion[]>(response);
}

/**
 * Fetch the layer catalogue for a selected region.
 */
export async function getRegionLayers(
  regionId: string,
): Promise<LayersResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/layers?region_id=${encodeURIComponent(regionId)}`,
    {
      method: "GET",
      cache: "no-store",
    },
  );

  return handleResponse<LayersResponse>(response);
}

/**
 * Send a route request to the FastAPI backend.
 */
export async function calculateRoute(
  request: RouteRequest,
): Promise<RouteResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/routes`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  return handleResponse<RouteResponse>(response);
}