import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 프론트엔드는 /api 로만 요청하고, 개발 서버가 FastAPI 백엔드로 넘긴다.
const backend = process.env.DOROTHY_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: backend, rewrite: (path) => path.replace(/^\/api/, "") },
    },
  },
});
