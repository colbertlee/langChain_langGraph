import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/globals.css';

// 在 React 挂载前同步读取持久化的主题，立刻应用到 <html>，
// 避免刷新时先闪深色再切到 light。
(function applyInitialTheme() {
  try {
    const raw = localStorage.getItem('agent-console-ui');
    if (!raw) return;
    const parsed = JSON.parse(raw) as { state?: { theme?: 'dark' | 'light' } };
    const t = parsed?.state?.theme;
    if (t === 'light') document.documentElement.classList.add('light');
  } catch {
    /* ignore */
  }
})();

let __errPre: HTMLPreElement | null = null;
function showErr(tag: string, msg: string, stack?: string) {
  if (!__errPre) {
    __errPre = document.createElement('pre');
    __errPre.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#400;color:#fee;padding:8px;font:10px monospace;white-space:pre-wrap;max-height:90vh;overflow:auto';
    document.body.appendChild(__errPre);
  }
  __errPre.textContent = `[${tag}] ${msg}\n${stack || ''}`;
}
window.addEventListener('error', (e) => showErr('error', e.message, e.error?.stack));
window.addEventListener('unhandledrejection', (e) =>
  showErr('rej', String(e.reason), (e.reason as Error)?.stack),
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
