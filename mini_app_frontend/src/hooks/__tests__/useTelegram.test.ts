import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useTelegram } from '../useTelegram';

describe('useTelegram', () => {
  it('should return isReady as true when WebApp exists', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.isReady).toBe(true);
  });

  it('should return user from initDataUnsafe', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.user).toMatchObject({
      id: 123456789,
      first_name: 'Test',
      username: 'testuser',
    });
  });

  it('should return start_param from initDataUnsafe', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.startParam).toBe('group_123');
  });

  it('should return colorScheme', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.colorScheme).toBe('light');
  });

  it('should provide hapticFeedback methods', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.hapticFeedback).toBeDefined();
    expect(result.current.hapticFeedback.impact).toBeInstanceOf(Function);
    expect(result.current.hapticFeedback.notification).toBeInstanceOf(Function);
    expect(result.current.hapticFeedback.selection).toBeInstanceOf(Function);
  });

  it('should call hapticFeedback.impact', () => {
    const { result } = renderHook(() => useTelegram());

    act(() => {
      result.current.hapticFeedback.impact('medium');
    });

    expect(window.Telegram?.WebApp?.HapticFeedback.impactOccurred).toHaveBeenCalledWith('medium');
  });

  it('should provide mainButton methods', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.mainButton).toBeDefined();
    expect(result.current.mainButton.show).toBeInstanceOf(Function);
    expect(result.current.mainButton.hide).toBeInstanceOf(Function);
  });

  it('should provide backButton methods', () => {
    const { result } = renderHook(() => useTelegram());

    expect(result.current.backButton).toBeDefined();
    expect(result.current.backButton.show).toBeInstanceOf(Function);
    expect(result.current.backButton.hide).toBeInstanceOf(Function);
  });

  it('should provide showConfirm that returns a promise', async () => {
    const { result } = renderHook(() => useTelegram());

    const confirmed = await result.current.showConfirm('Test message');

    expect(confirmed).toBe(true);
  });

  it('should provide showAlert that returns a promise', async () => {
    const { result } = renderHook(() => useTelegram());

    await expect(result.current.showAlert('Test alert')).resolves.toBeUndefined();
  });
});
