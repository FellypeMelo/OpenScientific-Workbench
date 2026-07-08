"use client";

import { useEffect, useRef } from "react";
import igv from "igv";
import type { Browser } from "igv";

const DEFAULT_GENOME = "hg38";
const DEFAULT_LOCUS = "chr8:127,736,588-127,739,371"; // MYC locus, a common demo region.

export interface IGVViewerProps {
  genome?: string;
  locus?: string;
}

/**
 * Mounts a real igv.js (https://igv.org/doc/igvjs) genome browser using a
 * built-in reference genome, replacing the previous build's empty placeholder
 * `<div>`.
 *
 * `igv` is imported statically here (matching igv.js's own official usage
 * examples, e.g. `import igv from "../../js/index.js"`), relying on the
 * `igv` -> `igv/dist/igv.esm.js` resolution alias configured in
 * `next.config.ts` for both webpack and Turbopack -- without that alias,
 * `igv`'s package.json `browser` field resolves to a UMD bundle whose default
 * export was observed to interop inconsistently (`undefined` at runtime in
 * some `next build` configurations) instead of the real ES module build.
 *
 * SSR-safety is provided by the caller (`components/VisualizerPanel.tsx`),
 * which wraps this component in `next/dynamic(..., { ssr: false })` so it is
 * never evaluated during server-side rendering.
 */
export function IGVViewer({ genome = DEFAULT_GENOME, locus = DEFAULT_LOCUS }: IGVViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const browserRef = useRef<Browser | null>(null);

  useEffect(() => {
    let disposed = false;

    async function init() {
      if (!containerRef.current) return;

      try {
        const browser = await igv.createBrowser(containerRef.current, {
          genome,
          locus,
        });

        if (disposed) {
          igv.removeBrowser(browser);
          return;
        }
        browserRef.current = browser;
      } catch (err) {
        console.error("IGVViewer: failed to initialize genome browser", err);
      }
    }

    init();

    return () => {
      disposed = true;
      if (browserRef.current) {
        igv.removeBrowser(browserRef.current);
        browserRef.current = null;
      }
    };
  }, [genome, locus]);

  return (
    <div
      data-testid="igv-viewer"
      ref={containerRef}
      className="relative w-full h-full rounded-xl overflow-hidden bg-[#07070a]"
    />
  );
}
