import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Data is considered fresh for 30 seconds
      staleTime: 30 * 1000,
      // Cache data for 5 minutes
      gcTime: 5 * 60 * 1000,
      // Retry failed requests up to 2 times with exponential backoff
      retry: 2,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
      // Refetch on window focus for fresh data
      refetchOnWindowFocus: true,
      // Don't refetch on reconnect automatically (we'll handle this manually)
      refetchOnReconnect: false,
      // Use offline-first mode for better UX
      networkMode: 'offlineFirst',
    },
    mutations: {
      // Retry mutations once on failure
      retry: 1,
      retryDelay: 1000,
      networkMode: 'offlineFirst',
    },
  },
});

// Query key factory for type-safe and consistent keys
export const queryKeys = {
  all: ['saqshy'] as const,

  // Group queries
  groups: () => [...queryKeys.all, 'groups'] as const,
  group: (groupId: number) => [...queryKeys.groups(), groupId] as const,
  groupSettings: (groupId: number) => [...queryKeys.group(groupId), 'settings'] as const,
  groupStats: (groupId: number, periodDays: number) =>
    [...queryKeys.group(groupId), 'stats', { periodDays }] as const,

  // Reviews
  reviews: (groupId: number) => [...queryKeys.group(groupId), 'reviews'] as const,

  // Users
  users: () => [...queryKeys.all, 'users'] as const,
  user: (userId: number) => [...queryKeys.users(), userId] as const,

  // Channels
  channels: () => [...queryKeys.all, 'channels'] as const,
  channelValidation: (channelId: string) =>
    [...queryKeys.channels(), 'validate', channelId] as const,
} as const;

// Type for query keys
export type QueryKeys = typeof queryKeys;
