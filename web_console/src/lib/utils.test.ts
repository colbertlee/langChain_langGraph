import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { cn, formatTime, formatRelative, uid } from './utils';

describe('cn', () => {
  it('合并类名', () => {
    expect(cn('a', 'b', false && 'c', 'd')).toBe('a b d');
  });
  it('接受对象 / 数组', () => {
    expect(cn('x', { y: true, z: false })).toBe('x y');
  });
});

describe('formatTime', () => {
  it('输出 HH:MM:SS', () => {
    const ts = new Date(2026, 0, 1, 3, 4, 5).getTime();
    expect(formatTime(ts)).toBe('03:04:05');
  });
  it('补零', () => {
    const ts = new Date(2026, 0, 1, 9, 0, 0).getTime();
    expect(formatTime(ts)).toBe('09:00:00');
  });
});

describe('formatRelative', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('1 分钟内显示「刚刚」', () => {
    vi.setSystemTime(new Date('2026-07-22T10:00:30Z'));
    expect(formatRelative(Date.now() - 10_000)).toBe('刚刚');
  });
  it('显示分钟', () => {
    vi.setSystemTime(new Date('2026-07-22T10:05:00Z'));
    expect(formatRelative(new Date('2026-07-22T10:00:00Z').getTime())).toBe('5 分钟前');
  });
  it('显示小时', () => {
    vi.setSystemTime(new Date('2026-07-22T13:00:00Z'));
    expect(formatRelative(new Date('2026-07-22T10:00:00Z').getTime())).toBe('3 小时前');
  });
  it('显示天', () => {
    vi.setSystemTime(new Date('2026-07-25T10:00:00Z'));
    expect(formatRelative(new Date('2026-07-22T10:00:00Z').getTime())).toBe('3 天前');
  });
});

describe('uid', () => {
  it('唯一且非空', () => {
    const set = new Set(Array.from({ length: 200 }, () => uid()));
    expect(set.size).toBe(200);
    for (const id of set) expect(id.length).toBeGreaterThan(0);
  });
});
