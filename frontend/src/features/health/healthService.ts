import { api } from '@/api/api'
import type { HealthResponse } from '@/api/schemas'

// The body of GET /api/health
export type Health = HealthResponse

export async function checkHealth() {
  const response = await api.get<Health>('/health')
  return response.data
}
