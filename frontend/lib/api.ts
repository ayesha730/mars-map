import type {
  RouteRequest,
  RouteResponse,
  ApiErrorResponse,
} from "@/types/api";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

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