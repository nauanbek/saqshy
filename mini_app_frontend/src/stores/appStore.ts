import { create } from 'zustand';

interface AppState {
  // Group context
  groupId: number | null;
  setGroupId: (id: number | null) => void;

  // Theme
  colorScheme: 'light' | 'dark';
  setColorScheme: (scheme: 'light' | 'dark') => void;

  // App state
  isInitialized: boolean;
  setInitialized: (initialized: boolean) => void;

  // Error state
  initError: string | null;
  setInitError: (error: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Group context
  groupId: null,
  setGroupId: (id) => set({ groupId: id }),

  // Theme - will be synced with Telegram
  colorScheme: 'light',
  setColorScheme: (scheme) => set({ colorScheme: scheme }),

  // App state
  isInitialized: false,
  setInitialized: (initialized) => set({ isInitialized: initialized }),

  // Error state
  initError: null,
  setInitError: (error) => set({ initError: error }),
}));

// Selectors for optimized re-renders
export const selectGroupId = (state: AppState) => state.groupId;
export const selectColorScheme = (state: AppState) => state.colorScheme;
export const selectIsInitialized = (state: AppState) => state.isInitialized;
export const selectInitError = (state: AppState) => state.initError;
