import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./MolstarViewer", () => ({
  MolstarViewer: (props: { pdbId?: string }) => (
    <div data-testid="mock-molstar" data-pdbid={props.pdbId ?? ""} />
  ),
}));
vi.mock("./IGVViewer", () => ({
  IGVViewer: (props: { genome?: string; locus?: string }) => (
    <div data-testid="mock-igv" data-genome={props.genome ?? ""} data-locus={props.locus ?? ""} />
  ),
}));
vi.mock("./ManuscriptEditor", () => ({
  ManuscriptEditor: () => <div data-testid="mock-manuscript" />,
}));

import { VisualizerPanel } from "./VisualizerPanel";

describe("VisualizerPanel", () => {
  it("shows the Molstar viewer by default and switches to IGV on tab click", async () => {
    const user = userEvent.setup();
    render(<VisualizerPanel />);

    expect(screen.getByTestId("visualizer-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("mock-molstar")).toBeInTheDocument();
    expect(screen.queryByTestId("mock-igv")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /IGV/i }));

    expect(await screen.findByTestId("mock-igv")).toBeInTheDocument();
    expect(screen.queryByTestId("mock-molstar")).not.toBeInTheDocument();
  });

  it("threads a job result's pdbId/genome/locus down to the viewers (RF-007)", async () => {
    const user = userEvent.setup();
    render(
      <VisualizerPanel result={{ pdbId: "6XYZ", genome: "hg19", locus: "chr1:100-200" }} />
    );

    expect(await screen.findByTestId("mock-molstar")).toHaveAttribute("data-pdbid", "6XYZ");

    await user.click(screen.getByRole("button", { name: /IGV/i }));

    const igv = await screen.findByTestId("mock-igv");
    expect(igv).toHaveAttribute("data-genome", "hg19");
    expect(igv).toHaveAttribute("data-locus", "chr1:100-200");
  });

  it("uses viewer demo defaults when no result is provided", async () => {
    render(<VisualizerPanel />);
    // No pdbId threaded -> the viewer receives undefined and applies its default.
    expect(await screen.findByTestId("mock-molstar")).toHaveAttribute("data-pdbid", "");
  });

  it("switches to the manuscript editor tab (RF-008)", async () => {
    const user = userEvent.setup();
    render(<VisualizerPanel />);

    expect(screen.queryByTestId("mock-manuscript")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Manuscrito/i }));

    expect(await screen.findByTestId("mock-manuscript")).toBeInTheDocument();
    // The viewer stage is unmounted while the editor owns the panel body.
    expect(screen.queryByTestId("mock-molstar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mock-igv")).not.toBeInTheDocument();
  });
});
