import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ManuscriptComment } from "./types";

// The editor calls the real fetch wrapper transitively; mock the two
// endpoints it uses so the test never touches the network.
const compileManuscript = vi.fn();
const critiqueManuscript = vi.fn();
vi.mock("@/lib/api-client", () => ({
  compileManuscript: (src: string) => compileManuscript(src),
  critiqueManuscript: (src: string) => critiqueManuscript(src),
}));

import { ManuscriptEditor } from "./ManuscriptEditor";

// jsdom implements neither createObjectURL nor revokeObjectURL.
beforeEach(() => {
  compileManuscript.mockReset();
  critiqueManuscript.mockReset();
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

  describe("RF-008: real backend-sourced critique", () => {
    it("shows the empty state by default -- no hardcoded demo comments", () => {
      render(<ManuscriptEditor />);

      expect(screen.getByTestId("critique-empty")).toHaveTextContent(
        "Nenhuma sugestão do revisor."
      );
      expect(critiqueManuscript).not.toHaveBeenCalled();
    });

    it("fetches real comments from the backend and renders them", async () => {
      const user = userEvent.setup();
      critiqueManuscript.mockResolvedValue([
        { id: "c1", target_text: "afinity", suggestion: "affinity", resolved: false },
      ]);
      render(<ManuscriptEditor initialSource="binding afinity was measured" />);

      await user.click(screen.getByTestId("critique-button"));

      expect(await screen.findByTestId("comment-c1")).toBeInTheDocument();
      expect(screen.getByTestId("comment-c1")).toHaveTextContent("afinity");
      expect(screen.getByTestId("comment-c1")).toHaveTextContent("affinity");
      expect(critiqueManuscript).toHaveBeenCalledWith("binding afinity was measured");
    });

    it("shows a loading state while the critique request is in flight", async () => {
      const user = userEvent.setup();
      let resolveCritique: (comments: unknown[]) => void = () => {};
      critiqueManuscript.mockReturnValue(
        new Promise((resolve) => {
          resolveCritique = resolve;
        })
      );
      render(<ManuscriptEditor />);

      const button = screen.getByTestId("critique-button") as HTMLButtonElement;
      await user.click(button);

      expect(button).toBeDisabled();
      expect(button).toHaveTextContent("Revisando...");

      resolveCritique([]);
      await waitFor(() => expect(button).not.toBeDisabled());
    });

    it("shows an error message when the critique request fails, without fabricating comments", async () => {
      const user = userEvent.setup();
      critiqueManuscript.mockRejectedValue(new Error("Missing DEEPSEEK_API_KEY"));
      render(<ManuscriptEditor />);

      await user.click(screen.getByTestId("critique-button"));

      expect(await screen.findByTestId("critique-error")).toHaveTextContent(
        "Missing DEEPSEEK_API_KEY"
      );
      expect(screen.getByTestId("critique-empty")).toBeInTheDocument();
    });

    it("a re-run replaces the previous critique results with the fresh ones", async () => {
      const user = userEvent.setup();
      critiqueManuscript.mockResolvedValueOnce([
        { id: "c1", target_text: "afinity", suggestion: "affinity", resolved: false },
      ]);
      render(<ManuscriptEditor initialSource="afinity value" />);

      await user.click(screen.getByTestId("critique-button"));
      expect(await screen.findByTestId("comment-c1")).toBeInTheDocument();

      critiqueManuscript.mockResolvedValueOnce([]);
      await user.click(screen.getByTestId("critique-button"));

      await waitFor(() => expect(screen.queryByTestId("comment-c1")).not.toBeInTheDocument());
      expect(screen.getByTestId("critique-empty")).toBeInTheDocument();
    });
  });
});
