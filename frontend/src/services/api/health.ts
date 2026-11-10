/**
 * Health check service for RollCall AI backend
 */

import { API_ENDPOINTS } from "@/config/api";
import { apiClient } from "@/services/api/client";
import type { HealthCheckResponse } from "@/types/api";

export async function checkBackendHealth(): Promise<HealthCheckResponse> {
  return apiClient.get<HealthCheckResponse>(API_ENDPOINTS.HEALTH);
}
