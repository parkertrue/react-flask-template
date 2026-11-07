import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/queryClient'

/**
 * A wrapper for render or renderHook that gives a component a fresh cache,
 * with the app's defaults, for code that runs outside AuthProvider (which
 * brings its own). Fresh per call, so no test sees another's data.
 */
export function queryWrapper(client = createQueryClient()) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}
