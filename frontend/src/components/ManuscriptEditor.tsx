"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { compileManuscript, critiqueManuscript } from "@/lib/api-client";
import { mapBackendComment, type ManuscriptComment } from "./types";

type Mode = "editor" | "preview";
type PreviewState = "idle" | "compiling" | "ready" | "error";
type CritiqueState = "idle" | "loading" | "error";

const DEFAULT_SOURCE = `\\documentclass{article}
\\begin{document}
\\title{Boltz-2 Binding Affinity Report}
\\maketitle

The predicted binding afinity of the ligand was -7.82 kcal/mol,
consistent with the reference structure.
\\end{document}
`;

export interface ManuscriptEditorProps {
  initialSource?: string;
  /** Starting critic comments. Defaults to none -- real comments come from a
   * live `POST /api/v1/manuscript/critique` call (RF-008), never a hardcoded
   * demo array; the empty state below covers "nothing to show yet". */
  initialComments?: ManuscriptComment[];
}

export function ManuscriptEditor({
  initialSource = DEFAULT_SOURCE,
  initialComments = [],
}: ManuscriptEditorProps = {}) {
  const [mode, setMode] = useState<Mode>("editor");
  const [source, setSource] = useState(initialSource);
  const [comments, setComments] = useState<ManuscriptComment[]>(initialComments);
  const [preview, setPreview] = useState<PreviewState>("idle");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [critiqueState, setCritiqueState] = useState<CritiqueState>("idle");
  const [critiqueError, setCritiqueError] = useState<string>("");
  const pdfUrlRef = useRef<string | null>(null);

  const revokePdf = useCallback(() => {
    if (pdfUrlRef.current) {
      URL.revokeObjectURL(pdfUrlRef.current);
      pdfUrlRef.current = null;
    }
  }, []);

  useEffect(() => revokePdf, [revokePdf]);

  const pendingCount = comments.filter((c) => !c.resolved).length;

  function applyCorrection(commentId: string) {
    setComments((prev) => {
      const target = prev.find((c) => c.id === commentId);
      if (!target || target.resolved) return prev;
      if (source.includes(target.targetText)) {
        setSource((src) => src.replace(target.targetText, target.suggestion));
      }
      return prev.map((c) => (c.id === commentId ? { ...c, resolved: true } : c));
    });
  }

  async function handleCompile() {
    setMode("preview");
    setPreview("compiling");
    setErrorMessage("");
    try {
      const blob = await compileManuscript(source);
      revokePdf();
      const url = URL.createObjectURL(blob);
      pdfUrlRef.current = url;
      setPdfUrl(url);
      setPreview("ready");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Falha ao compilar o manuscrito.");
      setPreview("error");
    }
  }

  // RF-008: real critic output, replacing the previous hardcoded
  // `DEFAULT_COMMENTS` demo array with a live `POST /api/v1/manuscript/critique`
  // call over the manuscript's current source.
  async function handleCritique() {
    setCritiqueState("loading");
    setCritiqueError("");
    try {
      const backendComments = await critiqueManuscript(source);
      setComments(backendComments.map(mapBackendComment));
      setCritiqueState("idle");
    } catch (err) {
      setCritiqueError(err instanceof Error ? err.message : "Falha ao revisar o manuscrito.");
      setCritiqueState("error");
    }
  }

  return (
    <div
      data-testid="manuscript-editor"
      className="flex-1 h-full min-h-0 flex flex-col bg-[#030305] text-[#ededf0]"
    >
      <header className="flex items-center justify-between border-b border-[#1a1a24] bg-[#0c0c0e] px-4 py-2.5">
        <div className="flex items-center gap-1">
          {(["editor", "preview"] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === m ? "bg-[#14261f] text-[#86ffcf]" : "text-[#707086] hover:text-[#a0a0b8]"
              }`}
            >
              {m === "editor" ? "Editor" : "Pré-visualização"}
            </button>
          ))}
          <span className="ml-2 text-xs text-[#707086]">
            {pendingCount > 0
              ? `${pendingCount} sugestão${pendingCount > 1 ? "es" : ""} do revisor`
              : "Revisão resolvida"}
          </span>
        </div>

        <button
          data-testid="compile-button"
          onClick={handleCompile}
          disabled={preview === "compiling"}
          className="rounded-md bg-[#86ffcf] px-3.5 py-1.5 text-sm font-semibold text-[#04120b] transition-colors hover:bg-[#9bffd8] active:translate-y-px disabled:opacity-50"
        >
          {preview === "compiling" ? "Compilando..." : "Compilar PDF"}
        </button>
      </header>

      {mode === "editor" ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,1fr)_300px]">
          <div className="flex min-h-0 flex-col">
            <div className="border-b border-[#141420] px-4 py-1.5 font-mono text-[11px] uppercase tracking-wide text-[#5a5a70]">
              main.tex
            </div>
            <textarea
              data-testid="latex-input"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              spellCheck={false}
              className="flex-1 resize-none bg-[#07070a] p-4 font-mono text-[13px] leading-relaxed text-[#d4d4dc] outline-none focus:ring-1 focus:ring-inset focus:ring-[#2a4d40]"
            />
          </div>

          <aside className="flex min-h-0 flex-col border-t border-[#1a1a24] md:border-l md:border-t-0 bg-[#0c0c0e]">
            <div className="flex items-center justify-between border-b border-[#141420] px-4 py-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#a0a0b8]">
                Revisor Crítico
              </span>
              <button
                data-testid="critique-button"
                onClick={handleCritique}
                disabled={critiqueState === "loading"}
                className="rounded-md border border-[#2a4d40] px-2.5 py-1 text-xs font-medium text-[#86ffcf] transition-colors hover:bg-[#0e1b16] disabled:opacity-50"
              >
                {critiqueState === "loading" ? "Revisando..." : "Revisar com IA"}
              </button>
            </div>
            {critiqueState === "error" && (
              <p data-testid="critique-error" className="px-3 pt-2 text-xs text-[#ff8686]">
                {critiqueError}
              </p>
            )}
            <div className="min-h-0 flex-1 overflow-auto p-3">
              {comments.length === 0 ? (
                <p data-testid="critique-empty" className="text-sm text-[#707086]">
                  {critiqueState === "loading"
                    ? "Revisando o manuscrito..."
                    : "Nenhuma sugestão do revisor."}
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {comments.map((c) => (
                    <li
                      key={c.id}
                      data-testid={`comment-${c.id}`}
                      className="rounded-lg border border-[#1c1c28] bg-[#080810] p-3"
                    >
                      <p className="font-mono text-xs text-[#ff9d9d] line-through break-words">
                        {c.targetText}
                      </p>
                      <p className="mt-1 font-mono text-xs text-[#86ffcf] break-words">
                        {c.suggestion}
                      </p>
                      {c.resolved ? (
                        <span className="mt-2 inline-block text-[11px] font-medium text-[#5a5a70]">
                          Resolvido
                        </span>
                      ) : (
                        <button
                          data-testid={`apply-${c.id}`}
                          onClick={() => applyCorrection(c.id)}
                          className="mt-2 rounded-md border border-[#2a4d40] px-2.5 py-1 text-xs font-medium text-[#86ffcf] transition-colors hover:bg-[#0e1b16]"
                        >
                          Aplicar correção
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>
      ) : (
        <div className="min-h-0 flex-1 p-4">
          <div className="flex h-full w-full items-center justify-center overflow-hidden rounded-xl border border-dashed border-[#242435] bg-[#07070a]">
            {preview === "idle" && (
              <p data-testid="preview-idle" className="px-8 text-center text-sm text-[#707086]">
                Compile o manuscrito para gerar a pré-visualização em PDF.
              </p>
            )}

            {preview === "compiling" && (
              <div data-testid="preview-compiling" className="w-full max-w-md px-8">
                <div className="flex flex-col gap-3">
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="h-3 animate-pulse rounded bg-[#141420]"
                      style={{ width: `${90 - i * 12}%` }}
                    />
                  ))}
                </div>
                <p className="mt-4 text-center text-xs text-[#5a5a70]">
                  Compilando com Tectonic...
                </p>
              </div>
            )}

            {preview === "error" && (
              <div data-testid="preview-error" className="max-w-md px-8 text-center">
                <p className="text-sm font-medium text-[#ff8686]">Não foi possível compilar.</p>
                <p className="mt-1 text-xs text-[#a0a0b8] break-words">{errorMessage}</p>
              </div>
            )}

            {preview === "ready" && pdfUrl && (
              <div data-testid="preview-ready" className="flex h-full w-full flex-col">
                <object data={pdfUrl} type="application/pdf" className="min-h-0 flex-1">
                  <div className="flex h-full items-center justify-center">
                    <a
                      href={pdfUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm font-medium text-[#86ffcf] hover:underline"
                    >
                      Abrir PDF em nova aba
                    </a>
                  </div>
                </object>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
