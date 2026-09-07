/**
 * v2.1 — ThemeSync
 *
 * 把 useUIStore.theme 同步到 <html class="dark"|"light">，
 * 让 globals.css 的 :root.light 重新定义 CSS 变量，从而切主题。
 *
 * 放在 React 树根（App 内部），不渲染任何 DOM。
 */
import { useEffect } from 'react';
import { useUIStore } from '@/stores/uiStore';

export function ThemeSync() {
  const theme = useUIStore((s) => s.theme);
  useEffect(() => {
    const root = document.documentElement;
    // 先清掉可能遗留的 dark / light，再用当前主题单源标识
    root.classList.remove('dark', 'light');
    root.classList.add(theme);
    // 强制 reflow，确保浏览器应用新类
    void root.offsetHeight;
  }, [theme]);
  return null;
}
