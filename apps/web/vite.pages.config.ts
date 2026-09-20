import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  root: resolve(import.meta.dirname, "pages"),
  publicDir: false,
  build: {
    outDir: resolve(import.meta.dirname, "../../site/workspace"),
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: { input: resolve(import.meta.dirname, "pages/index.html") },
  },
});
