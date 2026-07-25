import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach } from 'vitest';

// 跨测试清 localStorage 避免 zustand persist 污染
beforeEach(() => {
  try {
    localStorage.clear();
    sessionStorage.clear();
  } catch {
    /* noop */
  }
});
afterEach(() => {
  try {
    localStorage.clear();
    sessionStorage.clear();
  } catch {
    /* noop */
  }
});

// Mock window.matchMedia（assistant-ui / Tailwind 暗色可能用）
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// ResizeObserver / IntersectionObserver 兜底
class MockObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error 全局兜底
global.ResizeObserver = global.ResizeObserver || MockObserver;
// @ts-expect-error 全局兜底
global.IntersectionObserver = global.IntersectionObserver || MockObserver;
