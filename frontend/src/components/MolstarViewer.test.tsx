import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("molstar/lib/mol-plugin-ui", () => ({ createPluginUI: vi.fn() }));
vi.mock("molstar/lib/mol-plugin-ui/react18", () => ({ renderReact18: vi.fn() }));
vi.mock("molstar/lib/mol-plugin-ui/skin/light.scss", () => ({}));

import { createPluginUI } from "molstar/lib/mol-plugin-ui";

import { MolstarViewer } from "./MolstarViewer";

function buildMockPlugin() {
  const dispose = vi.fn();
  const download = vi.fn().mockResolvedValue("downloaded-data");
  const parseTrajectory = vi.fn().mockResolvedValue("trajectory");
  const applyPreset = vi.fn().mockResolvedValue(undefined);
  return {
    dispose,
    download,
    parseTrajectory,
    applyPreset,
    plugin: {
      dispose,
      builders: {
        data: { download },
        structure: {
          parseTrajectory,
          hierarchy: { applyPreset },
        },
      },
    },
  };
}

describe("MolstarViewer", () => {
  beforeEach(() => {
    vi.mocked(createPluginUI).mockReset();
  });

  it("mounts the container synchronously (no SSR/import-time WebGL dependency)", () => {
    vi.mocked(createPluginUI).mockReturnValue(new Promise(() => {})); // never resolves
    render(<MolstarViewer />);
    expect(screen.getByTestId("molstar-viewer")).toBeInTheDocument();
  });

  it("initializes the Mol* plugin and loads the requested PDB structure", async () => {
    const mock = buildMockPlugin();
    vi.mocked(createPluginUI).mockResolvedValue(mock.plugin as never);

    render(<MolstarViewer pdbId="1CRN" />);

    await waitFor(() => expect(createPluginUI).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(mock.download).toHaveBeenCalledWith(
        { url: "https://files.rcsb.org/download/1CRN.pdb" },
        { state: { isGhost: true } }
      )
    );
    await waitFor(() => expect(mock.parseTrajectory).toHaveBeenCalledWith("downloaded-data", "pdb"));
    await waitFor(() => expect(mock.applyPreset).toHaveBeenCalledWith("trajectory", "default"));
  });

  it("derives the RCSB download URL from the pdbId prop (RF-007)", async () => {
    const mock = buildMockPlugin();
    vi.mocked(createPluginUI).mockResolvedValue(mock.plugin as never);

    render(<MolstarViewer pdbId="6XYZ" />);

    await waitFor(() =>
      expect(mock.download).toHaveBeenCalledWith(
        { url: "https://files.rcsb.org/download/6XYZ.pdb" },
        { state: { isGhost: true } }
      )
    );
  });

  it("disposes the plugin instance on unmount", async () => {
    const mock = buildMockPlugin();
    vi.mocked(createPluginUI).mockResolvedValue(mock.plugin as never);

    const { unmount } = render(<MolstarViewer />);
    await waitFor(() => expect(createPluginUI).toHaveBeenCalledTimes(1));

    unmount();

    await waitFor(() => expect(mock.dispose).toHaveBeenCalledTimes(1));
  });
});
