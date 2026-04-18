import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { viteSingleFile } from "vite-plugin-singlefile";
import { resolve } from "node:path";

// Recall widget — single-entry, fully inlined HTML.
//
// Run via ``npm run build:recall`` (which ``npm run build`` chains after the
// dashboard build).  Appends ``dist/recall.html`` without touching the
// existing ``dist/index.html`` (``emptyOutDir: false``) so the dashboard and
// each widget coexist inside one ``dist/`` directory.  The
// ``src/distillery/mcp/resources.py`` inliner reads ``dist/<slug>.html``.
export default defineConfig({
  plugins: [svelte(), viteSingleFile()],
  build: {
    outDir: "dist",
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, "recall.html"),
    },
  },
  resolve: {
    alias: {
      $lib: resolve(__dirname, "src/lib"),
    },
  },
});
