import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useUIStore } from '../uiStore';

describe('uiStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useUIStore.setState({
      isGlobalLoading: false,
      toasts: [],
      activeModal: null,
      previousPage: null,
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('globalLoading', () => {
    it('should set global loading state', () => {
      useUIStore.getState().setGlobalLoading(true);
      expect(useUIStore.getState().isGlobalLoading).toBe(true);
    });
  });

  describe('toasts', () => {
    it('should add a toast', () => {
      const id = useUIStore.getState().addToast({
        type: 'success',
        message: 'Test message',
      });

      expect(id).toBeDefined();
      expect(useUIStore.getState().toasts).toHaveLength(1);
      expect(useUIStore.getState().toasts[0]).toMatchObject({
        type: 'success',
        message: 'Test message',
      });
    });

    it('should remove a toast', () => {
      const id = useUIStore.getState().addToast({
        type: 'error',
        message: 'Error message',
        duration: 0, // Disable auto-remove
      });

      expect(useUIStore.getState().toasts).toHaveLength(1);

      useUIStore.getState().removeToast(id);
      expect(useUIStore.getState().toasts).toHaveLength(0);
    });

    it('should auto-remove toast after duration', () => {
      useUIStore.getState().addToast({
        type: 'info',
        message: 'Auto remove test',
        duration: 2000,
      });

      expect(useUIStore.getState().toasts).toHaveLength(1);

      vi.advanceTimersByTime(2000);

      expect(useUIStore.getState().toasts).toHaveLength(0);
    });

    it('should clear all toasts', () => {
      useUIStore.getState().addToast({ type: 'success', message: 'Toast 1', duration: 0 });
      useUIStore.getState().addToast({ type: 'error', message: 'Toast 2', duration: 0 });
      useUIStore.getState().addToast({ type: 'warning', message: 'Toast 3', duration: 0 });

      expect(useUIStore.getState().toasts).toHaveLength(3);

      useUIStore.getState().clearToasts();
      expect(useUIStore.getState().toasts).toHaveLength(0);
    });
  });

  describe('modals', () => {
    it('should open a modal', () => {
      useUIStore.getState().openModal('settings');
      expect(useUIStore.getState().activeModal).toBe('settings');
    });

    it('should close a modal', () => {
      useUIStore.getState().openModal('settings');
      useUIStore.getState().closeModal();
      expect(useUIStore.getState().activeModal).toBeNull();
    });
  });

  describe('navigation', () => {
    it('should set previous page', () => {
      useUIStore.getState().setPreviousPage('/app/stats');
      expect(useUIStore.getState().previousPage).toBe('/app/stats');
    });
  });
});
