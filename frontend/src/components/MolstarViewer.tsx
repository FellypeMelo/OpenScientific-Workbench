"use client";

import { useEffect, useRef } from "react";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";

const DEFAULT_PDB_ID = "1CRN";

export interface MolstarViewerProps {
  /** RCSB PDB id to fetch and render on mount. Defaults to Crambin (1CRN), a
   * tiny, fast-loading, commonly-used Mol* demo structure. */
  pdbId?: string;
}

/**
 * Mounts a real Mol* (https://molstar.org) plugin instance with a WebGL canvas
 * and loads a structure fetched live from RCSB PDB -- replacing the previous
 * build's empty placeholder `<div>`.
 *
 * All Molstar imports happen dynamically *inside* `useEffect` (not at module
 * top-level) rather than via static `import` statements, so this module has
 * zero side effects at import/evaluation time:
 * - safe under Next.js SSR (Molstar touches `window`/WebGL at
 *   plugin-construction time, not at import time -- see
 *   https://github.com/molstar/molstar/blob/master/docs/docs/plugin/instance.md),
 * - safe to import from Vitest/jsdom component tests without needing a real
 *   WebGL context (tests mock the dynamically-imported modules instead).
 * The parent (`components/VisualizerPanel.tsx`) additionally wraps this
 * component in `next/dynamic(..., { ssr: false })` as a second, belt-and-braces
 * layer of SSR-safety.
 */
export function MolstarViewer({ pdbId = DEFAULT_PDB_ID }: MolstarViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pluginRef = useRef<PluginUIContext | null>(null);

  useEffect(() => {
    let disposed = false;

    async function init() {
      if (!containerRef.current) return;

      const [{ createPluginUI }, { renderReact18 }] = await Promise.all([
        import("molstar/lib/mol-plugin-ui"),
        import("molstar/lib/mol-plugin-ui/react18"),
        // Molstar's bundled default UI theme. Requires the `sass` package as a
        // build-time dependency for Next.js/webpack to process this `.scss`
        // import (see `frontend/package.json` devDependencies).
        import("molstar/lib/mol-plugin-ui/skin/light.scss"),
      ]);

      if (disposed || !containerRef.current) return;

      const plugin = await createPluginUI({
        target: containerRef.current,
        render: renderReact18,
      });

      if (disposed) {
        plugin.dispose();
        return;
      }
      pluginRef.current = plugin;

      try {
        const data = await plugin.builders.data.download(
          { url: `https://files.rcsb.org/download/${pdbId}.pdb` },
          { state: { isGhost: true } }
        );
        const trajectory = await plugin.builders.structure.parseTrajectory(data, "pdb");
        await plugin.builders.structure.hierarchy.applyPreset(trajectory, "default");
      } catch (err) {
        // A failed structure fetch (offline sandbox, RCSB unreachable, CORS in
        // some hosting setups, etc.) should leave an empty-but-initialized
        // viewer rather than crash the whole panel.
        console.error("MolstarViewer: failed to load structure", pdbId, err);
      }
    }

    init();

    return () => {
      disposed = true;
      pluginRef.current?.dispose();
      pluginRef.current = null;
    };
  }, [pdbId]);

  return (
    <div
      data-testid="molstar-viewer"
      ref={containerRef}
      className="relative w-full h-full rounded-xl overflow-hidden bg-[#07070a]"
    />
  );
}
