import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./MolstarViewer", () => ({
  MolstarViewer: () => <div data-testid="mock-molstar" />,
}));
vi.mock("./IGVViewer", () => ({
  IGVViewer: () => <div data-testid="mock-igv" />,
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
});
