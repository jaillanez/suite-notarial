import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from './api'

export const HEALTH_REFRESH_MS = 30_000

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: HEALTH_REFRESH_MS,
    retry: false,
  })
}
