import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ManuscriptComment } from "./types";

// The editor calls the real fetch wrapper transitively; mock the single
// endpoint it uses so the test never touches the network.
const compileManuscript = vi.fn();
vi.mock("@/lib/api-client", () => ({
  compileManuscript: (src: string) => compileManuscript(src),
}));

import { ManuscriptEditor } from "./ManuscriptEditor";

// jsdom implements neither createObjectURL nor revokeObjectURL.
beforeEach(() => {
  compileManuscript.mockReset();
  URL.createObjectURL = vi.fn(() => "blob:mock-pdf");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const COMMENTS: ManuscriptComment[] = [
  { id: "c1", targetText: "afinity", suggestion: "affinity" },
];

describe("ManuscriptEditor", () => {
  it("applies a critic correction in place and marks the comment resolved", async () => {
    const user = userEvent.setup();
    render(
      <ManuscriptEditor
        initialSource={"binding afinity was measured"}
        initialComments={COMMENTS}
      />
    );

    const textarea = screen.getByTestId("latex-input") as HTMLTextAreaElement;
    expect(textarea.value).toContain("afinity");

    await user.click(screen.getByTestId("apply-c1"));

    expect(textarea.value).toContain("affinity");
    expect(textarea.value).not.toContain("binding afinity");
    // The Apply button is replaced by a "Resolvido" marker.
    expect(screen.queryByTestId("apply-c1")).not.toBeInTheDocument();
    expect(screen.getByText(/Resolvido/i)).toBeInTheDocument();
  });

  it("compiles the source and shows the PDF preview on success", async () => {
    const user = userEvent.setup();
    compileManuscript.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
    render(<ManuscriptEditor initialComments={[]} />);

    await user.click(screen.getByTestId("compile-button"));

    expect(await screen.findByTestId("preview-ready")).toBeInTheDocument();
    expect(compileManuscript).toHaveBeenCalledOnce();
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
  });

  it("shows an error state when compilation fails", async () => {
    const user = userEvent.setup();
    compileManuscript.mockRejectedValue(new Error("tectonic not found"));
    render(<ManuscriptEditor initialComments={[]} />);

    await user.click(screen.getByTestId("compile-button"));

    const error = await screen.findByTestId("preview-error");
    expect(error).toHaveTextContent("tectonic not found");
  });

  it("keeps the compile button disabled while a compilation is in flight", async () => {
    const user = userEvent.setup();
    let resolveCompile: (blob: Blob) => void = () => {};
    compileManuscript.mockReturnValue(
      new Promise<Blob>((resolve) => {
        resolveCompile = resolve;
      })
    );
    render(<ManuscriptEditor initialComments={[]} />);

    const button = screen.getByTestId("compile-button") as HTMLButtonElement;
    await user.click(button);

    expect(screen.getByTestId("preview-compiling")).toBeInTheDocument();
    expect(button).toBeDisabled();

    resolveCompile(new Blob(["%PDF"], { type: "application/pdf" }));
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
