import type {
  GroupSettings,
  GroupStats,
  PendingReview,
  ReviewAction,
  ApiResponse,
  GroupInfo,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || '';
const DEFAULT_TIMEOUT = 30000; // 30 seconds
const MAX_RETRIES = 3;
const RETRY_DELAY_BASE = 1000; // 1 second

// Custom error classes for better error handling
export class ApiError extends Error {
  code: string;
  status?: number;

  constructor(code: string, message: string, status?: number) {
    super(message);
    this.code = code;
    this.status = status;
    this.name = 'ApiError';
  }
}

export class NetworkError extends Error {
  constructor(message: string = 'Network connection failed') {
    super(message);
    this.name = 'NetworkError';
  }
}

export class TimeoutError extends Error {
  constructor(message: string = 'Request timed out') {
    super(message);
    this.name = 'TimeoutError';
  }
}

// Helper to check if error is retryable
function isRetryableError(error: unknown): boolean {
  if (error instanceof TimeoutError) return true;
  if (error instanceof NetworkError) return true;
  if (error instanceof ApiError) {
    // Retry on server errors (5xx) but not client errors (4xx)
    return error.status !== undefined && error.status >= 500;
  }
  return false;
}

// Delay helper with exponential backoff
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Get Telegram init data from WebApp
function getInitData(): string {
  return window.Telegram?.WebApp?.initData || '';
}

// Main API request function with retry and timeout
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  retries: number = MAX_RETRIES
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE}/api${endpoint}`, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': getInitData(),
        ...options.headers,
      },
    });

    clearTimeout(timeoutId);

    // Parse response
    let data: ApiResponse<T>;
    try {
      data = await response.json();
    } catch {
      throw new ApiError('PARSE_ERROR', 'Failed to parse server response', response.status);
    }

    // Handle error responses
    if (!response.ok || !data.success) {
      const error = data.error || { code: 'UNKNOWN', message: 'Unknown error occurred' };
      throw new ApiError(error.code, error.message, response.status);
    }

    return data.data as T;
  } catch (error) {
    clearTimeout(timeoutId);

    // Handle abort (timeout)
    if (error instanceof DOMException && error.name === 'AbortError') {
      const timeoutError = new TimeoutError();
      if (retries > 0 && isRetryableError(timeoutError)) {
        const delayMs = RETRY_DELAY_BASE * Math.pow(2, MAX_RETRIES - retries);
        await delay(delayMs);
        return apiRequest(endpoint, options, retries - 1);
      }
      throw timeoutError;
    }

    // Handle network errors
    if (error instanceof TypeError && error.message.includes('fetch')) {
      const networkError = new NetworkError();
      if (retries > 0 && isRetryableError(networkError)) {
        const delayMs = RETRY_DELAY_BASE * Math.pow(2, MAX_RETRIES - retries);
        await delay(delayMs);
        return apiRequest(endpoint, options, retries - 1);
      }
      throw networkError;
    }

    // Retry server errors
    if (error instanceof ApiError && isRetryableError(error) && retries > 0) {
      const delayMs = RETRY_DELAY_BASE * Math.pow(2, MAX_RETRIES - retries);
      await delay(delayMs);
      return apiRequest(endpoint, options, retries - 1);
    }

    throw error;
  }
}

// ============ Group endpoints ============

export async function getGroupInfo(groupId: number): Promise<GroupInfo> {
  return apiRequest<GroupInfo>(`/groups/${groupId}`);
}

export async function getGroupSettings(groupId: number): Promise<GroupSettings> {
  return apiRequest<GroupSettings>(`/groups/${groupId}/settings`);
}

export async function updateGroupSettings(
  groupId: number,
  settings: Partial<GroupSettings>
): Promise<GroupSettings> {
  return apiRequest<GroupSettings>(`/groups/${groupId}/settings`, {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

export async function getGroupStats(groupId: number, periodDays: number = 7): Promise<GroupStats> {
  return apiRequest<GroupStats>(`/groups/${groupId}/stats?period_days=${periodDays}`);
}

// ============ Review endpoints ============

export async function getPendingReviews(groupId: number): Promise<PendingReview[]> {
  return apiRequest<PendingReview[]>(`/groups/${groupId}/reviews`);
}

export async function submitReviewAction(
  groupId: number,
  action: ReviewAction
): Promise<{ success: boolean }> {
  return apiRequest<{ success: boolean }>(`/groups/${groupId}/reviews`, {
    method: 'POST',
    body: JSON.stringify(action),
  });
}

// ============ Channel endpoints ============

export async function validateChannel(
  channelId: string
): Promise<{ valid: boolean; channel_id: number; title: string }> {
  return apiRequest<{ valid: boolean; channel_id: number; title: string }>(
    `/channels/validate?channel=${encodeURIComponent(channelId)}`
  );
}

// ============ Utility functions ============

// Check if we're online
export function isOnline(): boolean {
  return navigator.onLine;
}

// Create an online status listener
export function onOnlineStatusChange(callback: (online: boolean) => void): () => void {
  const handleOnline = () => callback(true);
  const handleOffline = () => callback(false);

  window.addEventListener('online', handleOnline);
  window.addEventListener('offline', handleOffline);

  return () => {
    window.removeEventListener('online', handleOnline);
    window.removeEventListener('offline', handleOffline);
  };
}
