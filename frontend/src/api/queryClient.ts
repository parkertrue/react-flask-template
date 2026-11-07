import { QueryClient } from '@tanstack/react-query'

// The cache of server data. AuthProvider owns the one instance and empties it
// whenever the signed-in account changes, so it never shows one user's data
// to the next.
//
// Off by default for queries (mutations never retry), each for a reason:
// - retry: the api client already refreshes an expired token, and a 503 or a
//   network error should show at once, not after three silent tries
// - refetch on focus or reconnect: a list refetched under the user would
//   reload every page they have loaded, and move the rows they are reading
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  })
}
