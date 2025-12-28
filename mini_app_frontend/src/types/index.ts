// Telegram WebApp types
export interface TelegramUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
}

export interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
  header_bg_color?: string;
  accent_text_color?: string;
  section_bg_color?: string;
  section_header_text_color?: string;
  subtitle_text_color?: string;
  destructive_text_color?: string;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    query_id?: string;
    user?: TelegramUser;
    auth_date?: number;
    hash?: string;
    start_param?: string;
  };
  themeParams: TelegramThemeParams;
  colorScheme: 'light' | 'dark';
  isExpanded: boolean;
  viewportHeight: number;
  viewportStableHeight: number;
  headerColor: string;
  backgroundColor: string;
  ready: () => void;
  expand: () => void;
  close: () => void;
  showConfirm: (message: string, callback: (confirmed: boolean) => void) => void;
  showAlert: (message: string, callback?: () => void) => void;
  // Event methods
  onEvent: (eventType: string, callback: (event: { isStateStable: boolean }) => void) => void;
  offEvent: (eventType: string, callback: (event: { isStateStable: boolean }) => void) => void;
  MainButton: {
    text: string;
    color: string;
    textColor: string;
    isVisible: boolean;
    isActive: boolean;
    isProgressVisible: boolean;
    setText: (text: string) => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
    show: () => void;
    hide: () => void;
    enable: () => void;
    disable: () => void;
    showProgress: (leaveActive?: boolean) => void;
    hideProgress: () => void;
  };
  BackButton: {
    isVisible: boolean;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
    show: () => void;
    hide: () => void;
  };
  HapticFeedback: {
    impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
    notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
    selectionChanged: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp;
    };
  }
}

// Group types
export type GroupType = 'general' | 'tech' | 'deals' | 'crypto';

export interface GroupTypeOption {
  value: GroupType;
  label: string;
  description: string;
  icon: string;
}

// API types
export interface GroupSettings {
  group_id: number;
  group_type: GroupType;
  linked_channel_id: number | null;
  sandbox_enabled: boolean;
  sandbox_duration_hours: number;
  admin_notifications: boolean;
  sensitivity: number; // 1-10 scale for detection sensitivity
  admin_alert_chat_id: number | null; // Optional chat ID for admin alerts
  custom_whitelist: string[];
  custom_blacklist: string[];
  created_at: string;
  updated_at: string;
}

export interface GroupStats {
  group_id: number;
  period_days: number;
  total_messages: number;
  allowed: number;
  watched: number;
  limited: number;
  reviewed: number;
  blocked: number;
  fp_count: number;
  fp_rate: number;
  group_type: GroupType;
  top_threat_types: ThreatType[];
}

export interface ThreatType {
  type: string;
  count: number;
}

export interface PendingReview {
  id: string;
  group_id: number;
  user_id: number;
  username: string | null;
  message_preview: string;
  risk_score: number;
  verdict: string;
  threat_types: string[];
  created_at: string;
  message_id: number;
}

export interface ReviewAction {
  review_id: string;
  action: 'approve' | 'confirm_block';
}

// API response types
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
  };
}

export interface GroupInfo {
  id: number;
  title: string;
  member_count: number;
  settings: GroupSettings;
}
