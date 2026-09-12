import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Dev server proxy /api sang Django, nên code frontend luôn gọi đường dẫn tương
// đối. Nhờ vậy không cần biến môi trường base-URL nào, và bản build tĩnh do
// Caddy phục vụ chạy đúng y như lúc dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    // Các bài kiểm thử tích hợp giao diện dựng nhiều lớp React Query và route.
    // Runner CI dùng chung tài nguyên có thể mất hơn mặc định 5 giây dù không
    // có request mạng hay vòng lặp chờ; 15 giây vẫn phát hiện được treo thật.
    testTimeout: 15_000,
  },
})
