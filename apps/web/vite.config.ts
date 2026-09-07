import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "T2D_");
  return {
    base: "/workspace/",
    server: {
      port: 5173,
      strictPort: true,
      // Development proxy only. No data-warehouse configuration reaches the browser.
      proxy: { "/v1/demo/csv": env.T2D_API_ORIGIN || "http://127.0.0.1:8000" },
    },
  };
});
