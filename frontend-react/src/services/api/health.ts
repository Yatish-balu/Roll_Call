import { apiClient } from "@/services/api/client";

export interface HealthResponse {
  status: string;
  environment: string;
  version: string;
}

export async function checkBackendHealth(): Promise<HealthResponse> {
  return apiClient.get<HealthResponse>("/health");
}

