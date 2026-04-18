import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { resolve } from "node:path";

// Legacy monolithic dashboard build.
//
// Phase 1 keeps the existing single-entry behaviour for the dashboard so
// behaviour of the current ``ui://distillery/dashboard`` resource is
// unchanged during the recall-widget prototype.
//
// Per-skill widgets each have their own Vite config
// (``vite.config.<slug>.ts``) that uses ``vite-plugin-singlefile`` to emit
// a fully self-contained HTML.  ``npm run build`` runs the dashboard build
// first, then every widget build on top of it (appending to ``dist/``).
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      $lib: resolve(__dirname, "src/lib"),
    },
  },
});
