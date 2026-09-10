/**
 * Vitest 全局 setup
 *
 * 作用：
 *  - 初始化 jsdom polyfill（如果某些测试需要 DOM API）
 *  - 配置 React testing-library（如需）
 *  - 给测试一个干净的环境基线
 *
 * 当前主要测试协议层（lib/ hooks/ stores/），不需要 React DOM；
 * 但提供 jsdom stub 以防未来引入组件测试。
 */
import { vi } from 'vitest';

// Polyfill TextEncoder / TextDecoder（Node 已有，但部分测试可能在 jsdom 下）
import { TextEncoder, TextDecoder } from 'node:util';
if (typeof globalThis.TextEncoder === 'undefined') {
  globalThis.TextEncoder = TextEncoder;
}
if (typeof globalThis.TextDecoder === 'undefined') {
  globalThis.TextDecoder = TextDecoder;
}

// jsdom 不带 matchMedia polyfill；前端用了响应式 hook（useTheme/useMediaQuery）
// 需要补一个 mock 让组件能正常挂载
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(), // deprecated
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// jsdom 不带 IntersectionObserver；很多组件（懒加载 / 折叠）用到
if (typeof window !== 'undefined' && !window.IntersectionObserver) {
  class MockIntersectionObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn(() => []);
    root = null;
    rootMargin = '';
    thresholds = [];
  }
  Object.defineProperty(window, 'IntersectionObserver', {
    writable: true,
    value: MockIntersectionObserver,
  });
  (globalThis as Record<string, unknown>).IntersectionObserver = MockIntersectionObserver;
}

// jsdom 不带 ResizeObserver
if (typeof window !== 'undefined' && !window.ResizeObserver) {
  class MockResizeObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  Object.defineProperty(window, 'ResizeObserver', {
    writable: true,
    value: MockResizeObserver,
  });
  (globalThis as Record<string, unknown>).ResizeObserver = MockResizeObserver;
}

// jsdom 不带 scrollTo
if (typeof window !== 'undefined' && !window.scrollTo) {
  Object.defineProperty(window, 'scrollTo', {
    writable: true,
    value: vi.fn(),
  });
}

// 静默 noise log（避免 ruff 误报）
const originalWarn = console.warn;
console.warn = (...args: unknown[]) => {
  const msg = String(args[0] ?? '');
  // 屏蔽某些第三方库的 deprecation warning
  if (
    msg.includes('[antd: compatible]') ||
    msg.includes('punycode')
  ) {
    return;
  }
  originalWarn(...args);
};

// 默认测试超时（不依赖 vitest.config 调整）
vi.setConfig({ hookTimeout: 10_000 });
