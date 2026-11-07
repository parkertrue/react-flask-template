import { api } from '@/api/api'

// The body of GET /api/health
export interface Health {
  status: string
}

export async function checkHealth() {
  const response = await api.get<Health>('/health')
  return response.data
}
