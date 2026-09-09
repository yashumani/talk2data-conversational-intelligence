import { defineConfig } from "vite";

export default defineConfig({ root: "internal", base: "/workspace/", build: { outDir: "../dist-internal", emptyOutDir: true } });
