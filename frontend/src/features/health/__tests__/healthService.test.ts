import { describe, it, expect, vi } from 'vitest'
import { checkHealth } from '../healthService'
import { api } from '@/api/api'

vi.mock('@/api/api')

describe('healthService', () => {
  describe('checkHealth', () => {
    it('should call GET /health and return its body', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: { status: 'ok' } })

      const result = await checkHealth()

      expect(api.get).toHaveBeenCalledWith('/health')
      expect(result).toEqual({ status: 'ok' })
    })

    it('should propagate errors from API', async () => {
      const error = new Error('Health check failed')
      vi.mocked(api.get).mockRejectedValue(error)

      await expect(checkHealth()).rejects.toThrow('Health check failed')
    })
  })
})
