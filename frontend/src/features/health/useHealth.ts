import { useQuery } from '@tanstack/react-query'
import { checkHealth } from './healthService'

// The API's status, checked on mount and every 30 seconds while the page is
// visible. "checking" shows on the first check only: a poll keeps the last
// answer until it gets a new one, so the status line changes, and is read
// out, only when the API does.
export function useHealth() {
  const { data, isError } = useQuery({
    queryKey: ['health'],
    queryFn: checkHealth,
    refetchInterval: 30000,
  })

  if (isError) return 'error'
  return data?.status ?? 'checking'
}
