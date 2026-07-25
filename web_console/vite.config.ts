import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // 手动分 chunk：把大依赖拆开并行加载，主 bundle 减小
        manualChunks: (id) => {
          if (id.includes('node_modules')) {
            // 1. assistant-ui 体系（最大）
            if (
              id.includes('@assistant-ui') ||
              id.includes('@assistant-stream') ||
              id.includes('assistant-stream')
            ) {
              return 'vendor-aui';
            }
            // 2. react-syntax-highlighter + prism 单独（只在 markdown 代码块用到）
            if (
              id.includes('react-syntax-highlighter') ||
              id.includes('/refractor') ||
              id.includes('prismjs')
            ) {
              return 'vendor-prism';
            }
            // 3. react-markdown 体系
            if (
              id.includes('react-markdown') ||
              id.includes('remark') ||
              id.includes('rehype') ||
              id.includes('mdast') ||
              id.includes('micromark') ||
              id.includes('unist')
            ) {
              return 'vendor-markdown';
            }
            // 4. react / react-dom
            if (id.includes('react-dom') || id.includes('/react/')) {
              return 'vendor-react';
            }
            // 5. lucide-react 图标（按需打包后体量小，但保留独立 chunk）
            if (id.includes('lucide-react')) {
              return 'vendor-icons';
            }
            // 6. zustand
            if (id.includes('zustand')) {
              return 'vendor-zustand';
            }
            // 7. framer-motion（目前未使用但保留）
            if (id.includes('framer-motion')) {
              return 'vendor-motion';
            }
            // 8. clsx
            if (id.includes('clsx')) {
              return 'vendor-utils';
            }
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});