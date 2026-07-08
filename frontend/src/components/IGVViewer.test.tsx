import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("igv", () => ({
  default: {
    createBrowser: vi.fn(),
    removeBrowser: vi.fn(),
  },
}));

import igv from "igv";

import { IGVViewer } from "./IGVViewer";

describe("IGVViewer", () => {
  beforeEach(() => {
    vi.mocked(igv.createBrowser).mockReset();
    vi.mocked(igv.removeBrowser).mockReset();
  });

  it("mounts the container and creates a genome browser with the default genome/locus", async () => {
    const browser = { toJSON: vi.fn() };
    vi.mocked(igv.createBrowser).mockResolvedValue(browser as never);

    render(<IGVViewer />);
    expect(screen.getByTestId("igv-viewer")).toBeInTheDocument();

    await waitFor(() => expect(igv.createBrowser).toHaveBeenCalledTimes(1));
    const [container, options] = vi.mocked(igv.createBrowser).mock.calls[0];
    expect(container).toBeInstanceOf(HTMLElement);
    expect(options).toEqual({ genome: "hg38", locus: "chr8:127,736,588-127,739,371" });
  });

  it("honors custom genome/locus props", async () => {
    vi.mocked(igv.createBrowser).mockResolvedValue({} as never);

    render(<IGVViewer genome="hg19" locus="chr1:1-1000" />);

    await waitFor(() =>
      expect(igv.createBrowser).toHaveBeenCalledWith(expect.any(HTMLElement), {
        genome: "hg19",
        locus: "chr1:1-1000",
      })
    );
  });

  it("removes the browser instance on unmount", async () => {
    const browser = { toJSON: vi.fn() };
    vi.mocked(igv.createBrowser).mockResolvedValue(browser as never);

    const { unmount } = render(<IGVViewer />);
    await waitFor(() => expect(igv.createBrowser).toHaveBeenCalledTimes(1));

    unmount();

    await waitFor(() => expect(igv.removeBrowser).toHaveBeenCalledWith(browser));
  });
});
