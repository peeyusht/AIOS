// The fleet server's console: a second entry page built from this same source tree, so it shares the
// components and styles of the PC's own console. The server's Dockerfile runs this build (npm run build:fleet).
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./", // the server serves index.html at / and everything else from ./assets
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "dist-fleet", emptyOutDir: true, sourcemap: false,
    rollupOptions: { input: fileURLToPath(new URL("./fleet.html", import.meta.url)) },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8770" } },
});
