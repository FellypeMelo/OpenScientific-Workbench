import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Containerized deployment (Fase 6 - gap closure): emit the minimal
  // `.next/standalone` server bundle (just the traced production
  // `node_modules` subset + a small `server.js`) instead of requiring the
  // full `node_modules` tree + source in the runtime image. See
  // `frontend/Dockerfile`'s `runner` stage, which runs
  // `node .next/standalone/server.js` (NOT `next start` -- Next.js itself
  // warns that `next start` does not honor `output: "standalone"`) and
  // manually copies `public/` + `.next/static/` alongside it, per Next's own
  // docs (these two directories are deliberately left out of the standalone
  // trace so they can be served by a CDN instead, when one is in front of
  // this deployment).
  output: "standalone",

  // `igv`'s package.json advertises a `browser` field (`dist/igv.js`, a UMD
  // bundle targeting `<script>`/global usage) as well as a `module` field
  // (`dist/igv.esm.js`, a real ES module with a clean `export default`).
  // Both webpack and Turbopack prefer the `browser` field for client bundles
  // by default, and that UMD wrapper was observed to resolve inconsistently
  // through ESM default-import interop in `components/IGVViewer.tsx`
  // (`.default`/namespace access resolving to `undefined` at runtime despite
  // compiling without errors). Forcing resolution straight to the real ESM
  // build file sidesteps that interop ambiguity entirely, for both bundlers.
  // (Kept for both bundlers even though `package.json` currently pins scripts
  // to `--webpack` -- see note below -- so nothing breaks if that pin is
  // later lifted.)
  turbopack: {
    resolveAlias: {
      igv: "igv/dist/igv.esm.js",
    },
  },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      igv: "igv/dist/igv.esm.js",
    };
    return config;
  },
};

// Bundler note (Fase 5 - frontend gap closure): Next.js 16 defaults `next dev`
// / `next build` to Turbopack. With this project's dependencies (in
// particular Molstar's large/complex module graph pulled in by
// `components/MolstarViewer.tsx`), the default Turbopack production build was
// observed to throw a runtime `Module ... was instantiated ... but the module
// factory is not available` error when that chunk loaded in a real browser,
// even though `next build` itself reported success. `next build --webpack`
// (the classic, battle-tested bundler, still fully supported via Next's own
// `--webpack` CLI flag) was verified end-to-end instead: real headless
// Chromium (Playwright) renders both a genuine Mol* plugin UI (falling back
// to Mol*'s own "WebGL does not seem to be available" message in this
// particular sandbox, not a crash) and a real igv.js genome browser with live
// controls. `package.json`'s `dev`/`build` scripts are pinned to `--webpack`
// for that reason -- revisit this once Turbopack's production bundler
// matures further for heavy WebGL/worker-using dependencies like Molstar.
export default nextConfig;
