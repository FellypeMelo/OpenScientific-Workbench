"use client";

import { useState } from "react";
import dynamic from "next/dynamic";

import type { VisualizationResult } from "./types";

// Both viewers touch `window`/WebGL/canvas at plugin-construction time and are
// heavy (Molstar + igv.js pull in a substantial amount of JS). `next/dynamic`
// with `ssr: false` keeps them out of the server render entirely (belt and
// braces alongside the dynamic-import-inside-useEffect pattern already used
// inside each component -- see their module docstrings) and code-splits them
// out of the initial bundle.
const MolstarViewer = dynamic(
  () => import("./MolstarViewer").then((mod) => mod.MolstarViewer),
  {
    ssr: false,
    loading: () => (
      <div className="text-[#707086] text-sm">Carregando visualizador 3D...</div>
    ),
  }
);

const IGVViewer = dynamic(() => import("./IGVViewer").then((mod) => mod.IGVViewer), {
  ssr: false,
  loading: () => <div className="text-[#707086] text-sm">Carregando trilhas genômicas...</div>,
});

type Tab = "molstar" | "igv";

export interface VisualizerPanelProps {
  /** Job-derived data to render; falls back to each viewer's demo default. */
  result?: VisualizationResult;
}

export function VisualizerPanel({ result }: VisualizerPanelProps = {}) {
  const [activeTab, setActiveTab] = useState<Tab>("molstar");

  return (
    <div data-testid="visualizer-panel" className="flex-1 h-full bg-[#030305] flex flex-col">
      <div className="flex border-b border-[#1a1a24] bg-[#0c0c0e]">
        <button
          onClick={() => setActiveTab("molstar")}
          className={`px-4 py-3 text-sm font-medium transition-all ${
            activeTab === "molstar"
              ? "border-b-2 border-[#86ffcf] text-[#86ffcf]"
              : "text-[#707086]"
          }`}
        >
          Molstar (Proteins 3D)
        </button>
        <button
          onClick={() => setActiveTab("igv")}
          className={`px-4 py-3 text-sm font-medium transition-all ${
            activeTab === "igv" ? "border-b-2 border-[#86ffcf] text-[#86ffcf]" : "text-[#707086]"
          }`}
        >
          IGV (Genomic Tracks)
        </button>
      </div>

      <div className="flex-1 relative flex items-center justify-center p-8">
        <div className="w-full h-full border border-dashed border-[#242435] rounded-xl overflow-hidden bg-[#07070a] shadow-inner">
          {/* Only the active tab's viewer is mounted at a time -- each owns a
              real WebGL/canvas context (Molstar) or a heavy DOM tree (igv.js),
              so keeping both alive simultaneously would waste GPU contexts and
              double the network fetches for no visible benefit. */}
          {activeTab === "molstar" ? (
            <MolstarViewer pdbId={result?.pdbId} />
          ) : (
            <IGVViewer genome={result?.genome} locus={result?.locus} />
          )}
        </div>
      </div>
    </div>
  );
}
