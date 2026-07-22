"""Molecular cloning & DNA engineering action tools (Fase 5).

Implements every tool listed under `action_tool_catalog.md`'s "Categoria:
Molecular cloning & DNA engineering" heading, which the catalog blanket-tags
**Tier A** ("biopython/Bio.Restriction real logic") -- there is no Tier D
tool in this category (nothing here needs a proprietary pretrained
checkpoint or a GPU cluster), so every handler below routes through
`run_in_sandbox` and none raise `NotSupportedError`.

Registered tool names (`register_cloning_tools`):
    annotate_open_reading_frames, annotate_plasmid, get_gene_coding_sequence,
    get_plasmid_sequence, align_sequences, pcr_simple,
    pcr_complex_multi_primers, digest_sequence, golden_gate, oligo_assembly,
    gibson_assembly, find_restriction_sites, find_restriction_enzymes,
    design_primers_with_overhangs, find_sequence_mutations,
    get_molecular_cloning_instructions, calculate_element_distances,
    design_knockout_sgrna, design_golden_gate_oligos,
    get_oligo_annealing_protocol, get_golden_gate_assembly_protocol,
    get_bacterial_transformation_protocol, design_primer,
    design_verification_primers.

Every handler follows the same shape: validate `arguments` with a Pydantic
model (raises `pydantic.ValidationError`, itself a `ValueError` subclass,
BEFORE any sandbox call happens -- see `presentation/routes/mcp.py`'s
existing `ValueError` -> HTTP 400 mapping), then build a short, real,
hand-written `script_body` (real Biopython/`Bio.Restriction` calls -- the
actual scientific logic) and dispatch it via
`_sandbox_tool_base.run_in_sandbox`, which writes `arguments` to a JSON file
the sandboxed script reads back as `_args` (data, never spliced into the
script source as code -- see that module's docstring for the full threat
model this defends against).

Three tools carry documented, non-fabricated caveats instead of a blanket
"just works" claim -- consistent with `UNSUPPORTED.md`'s existing
"Partially supported" precedent (`predict_admet_properties` et al.), though
none of these three are Tier D so none get a new row there:

- `get_gene_coding_sequence` / `get_plasmid_sequence` -- real NCBI Entrez
  (and, for `get_plasmid_sequence`'s Addgene branch, a real but fragile
  page-scrape) calls that need outbound network access. The bwrap sandbox
  defaults to `--unshare-net` (`bubblewrap_driver.py`); these two tools only
  succeed when dispatched through a `driver` built with
  `allow_network=True`. Wiring which driver instance backs a given tool call
  is `presentation/dependencies.py`'s concern, out of scope here.
- `design_knockout_sgrna` -- looks up real, pre-validated guides from a
  bundled per-species sgRNA library expected at
  `/datalake/sgrna_library_<species>.csv`. As of this writing no such file
  is listed in `data_lake/MANIFEST.md`, so this tool currently always fails
  loud with a message pointing at `backend/scripts/fetch_data_lake.py`
  rather than fabricating a guide sequence -- exactly what
  `action_tool_catalog.md` asks for this entry.
"""
import functools
import textwrap
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from src.domain.services.path_guard import PathTraversalError, ensure_safe_relative_path
from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox

# --------------------------------------------------------------------------
# Argument models
# --------------------------------------------------------------------------


class _NoArgs(BaseModel):
    """Shared empty model for the two static, zero-parameter protocol tools
    (`get_molecular_cloning_instructions`, `get_oligo_annealing_protocol`)."""


class _FragmentSpec(BaseModel):
    """One input fragment for `golden_gate`."""

    sequence: str
    name: Optional[str] = None


class _ElementPosition(BaseModel):
    """One annotated element for `calculate_element_distances`."""

    start: int
    end: int
    name: Optional[str] = None


class AnnotateOpenReadingFramesArgs(BaseModel):
    sequence: str
    min_length: int
    search_reverse: bool = False
    filter_subsets: bool = False


class AnnotatePlasmidArgs(BaseModel):
    sequence: str
    is_circular: bool = True
    return_plot: bool = False


class GetGeneCodingSequenceArgs(BaseModel):
    gene_name: str
    organism: str
    email: Optional[str] = None


class GetPlasmidSequenceArgs(BaseModel):
    identifier: str
    is_addgene: Optional[bool] = None


class AlignSequencesArgs(BaseModel):
    long_seq: str
    short_seqs: Union[str, List[str]]


class PcrSimpleArgs(BaseModel):
    sequence: str
    forward_primer: str
    reverse_primer: str
    circular: bool = False


class PcrComplexMultiPrimersArgs(BaseModel):
    sequence: str
    primers: List[str]
    circular: bool = True


class DigestSequenceArgs(BaseModel):
    dna_sequence: str
    enzyme_names: List[str]
    is_circular: bool = True


class GoldenGateArgs(BaseModel):
    fragments: List[_FragmentSpec]
    circular: List[bool]
    enzyme_name: str


class OligoAssemblyArgs(BaseModel):
    seq1: str
    seq2: str


class GibsonAssemblyArgs(BaseModel):
    fragments: List[str]
    min_overlap: int = 15


class FindRestrictionSitesArgs(BaseModel):
    dna_sequence: str
    enzymes: List[str]
    is_circular: bool = True


class FindRestrictionEnzymesArgs(BaseModel):
    sequence: str
    is_circular: bool = False


class DesignPrimersWithOverhangsArgs(BaseModel):
    sequence: str
    forward_overhang: str
    reverse_overhang: str
    target_tm: float
    min_primer_length: int = 15


class FindSequenceMutationsArgs(BaseModel):
    query_sequence: str
    reference_sequence: str
    query_start: int = 1


class CalculateElementDistancesArgs(BaseModel):
    sequence_length: int
    element_positions: List[_ElementPosition]
    is_circular: bool = True


class DesignKnockoutSgrnaArgs(BaseModel):
    gene_name: str
    species: str = "human"
    num_guides: int = 1


class DesignGoldenGateOligosArgs(BaseModel):
    insert_sequence: str
    backbone_sequence: str
    enzyme_name: str = "BsmBI"
    is_circular: bool = True


class GetGoldenGateAssemblyProtocolArgs(BaseModel):
    enzyme_name: str
    vector_length: int
    num_inserts: int = 1
    vector_amount_ng: float = 75.0
    insert_lengths: Optional[List[int]] = None
    is_library_prep: bool = False


class GetBacterialTransformationProtocolArgs(BaseModel):
    antibiotic: str = "ampicillin"
    is_repetitive: bool = False


class DesignPrimerArgs(BaseModel):
    sequence: str
    start_pos: int
    primer_length: int = 20
    min_gc: float = 0.4
    max_gc: float = 0.6
    min_tm: float = 55.0
    max_tm: float = 65.0
    search_window: int = 100


class DesignVerificationPrimersArgs(BaseModel):
    plasmid_sequence: str
    target_region: Tuple[int, int]
    existing_primers: Optional[List[Dict[str, Any]]] = None
    is_circular: bool = True
    coverage_length: int = 800
    primer_length: int = 20
    min_gc: float = 0.4
    max_gc: float = 0.6
    min_tm: float = 55.0
    max_tm: float = 65.0


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def annotate_open_reading_frames(arguments: dict, driver) -> dict:
    """Finds all open reading frames (ORFs) in ``sequence`` with a real
    stop-to-stop / ATG-to-stop scan across the 3 forward reading frames, and
    (when ``search_reverse``) the 3 reverse-complement frames too. Tier A --
    deterministic sequence-scanning logic (no statistical model).

    ORF definition used here (documented, not a black box): within each
    reading frame, every in-frame ATG is a candidate ORF start; its end is
    the next in-frame stop codon. ``min_length`` is nucleotide length
    (inclusive of the stop codon). ``filter_subsets`` drops any ORF whose
    (start, end) interval is fully nested within a longer same-frame,
    same-strand ORF's interval.
    """
    args = AnnotateOpenReadingFramesArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq

        _STOPS = {"TAA", "TAG", "TGA"}


        def _scan_frames(seq_str, strand, min_length):
            orfs = []
            n = len(seq_str)
            for frame in range(3):
                starts = []
                pos = frame
                while pos + 3 <= n:
                    codon = seq_str[pos:pos + 3]
                    if codon == "ATG":
                        starts.append(pos)
                    if codon in _STOPS:
                        for s in starts:
                            end = pos + 3
                            length = end - s
                            if length >= min_length:
                                orfs.append({
                                    "start": s,
                                    "end": end,
                                    "length_nt": length,
                                    "frame": frame,
                                    "strand": strand,
                                    "protein": str(Seq(seq_str[s:end]).translate(to_stop=False)),
                                })
                        starts = []
                    pos += 3
            return orfs


        def _filter_subsets(orfs):
            kept = []
            for i, a in enumerate(orfs):
                contained = False
                for j, b in enumerate(orfs):
                    if i == j:
                        continue
                    same_strand_frame = a["strand"] == b["strand"] and a["frame"] == b["frame"]
                    bigger = (b["end"] - b["start"]) > (a["end"] - a["start"])
                    nested = b["start"] <= a["start"] and b["end"] >= a["end"]
                    if same_strand_frame and bigger and nested:
                        contained = True
                        break
                if not contained:
                    kept.append(a)
            return kept


        _sequence = _args["sequence"].upper()
        _min_length = _args["min_length"]
        _orfs = _scan_frames(_sequence, "+", _min_length)
        if _args.get("search_reverse"):
            _rc = str(Seq(_sequence).reverse_complement())
            _orfs += _scan_frames(_rc, "-", _min_length)

        if _args.get("filter_subsets"):
            _orfs = _filter_subsets(_orfs)

        _orfs.sort(key=lambda o: (-o["length_nt"], o["start"]))
        print(_json.dumps({"orfs": _orfs, "num_orfs": len(_orfs)}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def annotate_plasmid(arguments: dict, driver) -> dict:
    """Annotates a DNA sequence (ori, resistance markers, promoters, ...)
    via the real `pLannotate` CLI (`plannotate` conda package, already in
    `backend/sandbox/environment.yml`). Tier A -- calls a real, published
    annotation tool, not a fabricated feature list.

    NOTE on the exact CLI invocation: hand-transcribed from pLannotate's
    documented `batch` subcommand interface, not independently re-verified
    against a built sandbox-toolkit image in this session (same caveat
    `environment.yml`'s own header calls out for its other CLI entries) --
    if a built image's `plannotate --help` disagrees, fix the `argv` list
    below; the JSON args plumbing does not change.
    """
    args = AnnotatePlasmidArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        import csv
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as _tmpdir:
            _fasta_path = os.path.join(_tmpdir, "input.fasta")
            with open(_fasta_path, "w", encoding="utf-8") as _fh:
                _fh.write(">query\\n")
                _fh.write(_args["sequence"].upper() + "\\n")

            _argv = [
                "plannotate", "batch",
                "--input", _fasta_path,
                "--output", _tmpdir,
                "--file_name", "result",
            ]
            if not _args.get("is_circular", True):
                _argv.append("--linear")

            _proc = subprocess.run(_argv, capture_output=True, text=True)
            if _proc.returncode != 0:
                raise RuntimeError(f"plannotate CLI failed (exit {_proc.returncode}): {_proc.stderr}")

            _csv_path = os.path.join(_tmpdir, "result.csv")
            _features = []
            if os.path.exists(_csv_path):
                with open(_csv_path, newline="", encoding="utf-8") as _fh:
                    _features = list(csv.DictReader(_fh))

            _result = {
                "features": _features,
                "num_features": len(_features),
                "is_circular": _args.get("is_circular", True),
            }
            if _args.get("return_plot"):
                _svg_path = os.path.join(_tmpdir, "result.svg")
                if os.path.exists(_svg_path):
                    with open(_svg_path, encoding="utf-8") as _fh:
                        _result["plot_svg"] = _fh.read()
            print(_json.dumps(_result))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def get_gene_coding_sequence(arguments: dict, driver) -> dict:
    """Retrieves a gene's coding sequence (CDS) from the real NCBI Entrez
    nucleotide database (`Bio.Entrez`/`Bio.SeqIO`). Tier A -- real Entrez
    API call, same trust tier as `bio_direct_adapters.py`'s network calls,
    just executed inside the sandbox instead of in-process.

    NETWORK CAVEAT: NCBI Entrez needs outbound HTTPS. The bwrap sandbox
    defaults to `--unshare-net`; this tool only succeeds when dispatched
    through a `driver` built with `allow_network=True` -- same caveat
    `UNSUPPORTED.md` already documents for `predict_admet_properties`.
    """
    args = GetGeneCodingSequenceArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio import Entrez, SeqIO

        Entrez.email = _args.get("email") or "anonymous@openscientific-workbench.local"
        _term = (
            f'{_args["gene_name"]}[Gene Name] AND {_args["organism"]}[Organism] '
            'AND biomol_mrna[PROP] AND RefSeq[Filter]'
        )
        _handle = Entrez.esearch(db="nucleotide", term=_term, retmax=5)
        _search = Entrez.read(_handle)
        _handle.close()
        _ids = _search.get("IdList", [])
        if not _ids:
            raise ValueError(
                f"No NCBI nucleotide record found for gene={_args['gene_name']!r} "
                f"organism={_args['organism']!r}."
            )

        _fetch_handle = Entrez.efetch(db="nucleotide", id=_ids[0], rettype="gb", retmode="text")
        _record = SeqIO.read(_fetch_handle, "genbank")
        _fetch_handle.close()

        _cds_feature = next((f for f in _record.features if f.type == "CDS"), None)
        if _cds_feature is None:
            raise ValueError(f"NCBI record {_record.id} has no annotated CDS feature.")

        _cds_seq = str(_cds_feature.extract(_record.seq))
        print(_json.dumps({
            "gene_name": _args["gene_name"],
            "organism": _args["organism"],
            "ncbi_id": _record.id,
            "coding_sequence": _cds_seq,
            "length": len(_cds_seq),
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def get_plasmid_sequence(arguments: dict, driver) -> dict:
    """Unified Addgene/NCBI plasmid sequence lookup. Tier A, with a
    documented fragility caveat on the Addgene branch (same honesty
    standard as `query_scholar` in the literature-tools category): Addgene
    has no official public sequence-download REST API, so that branch
    scrapes the plasmid's public `/sequences/` page for its depositor-full
    GenBank download link (`requests` + `beautifulsoup4`, both already in
    `sandbox/requirements-pip.txt`) -- an upstream page-layout change can
    break this. The NCBI branch is a real, stable `Bio.Entrez.efetch` call.

    NETWORK CAVEAT: like `get_gene_coding_sequence`, this only succeeds
    against a `driver` built with `allow_network=True`.

    ``is_addgene``: when omitted, an all-digit ``identifier`` (Addgene's own
    plasmid-ID convention) is treated as Addgene; anything else as an NCBI
    accession.
    """
    args = GetPlasmidSequenceArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        import io

        import requests
        from bs4 import BeautifulSoup
        from Bio import Entrez, SeqIO

        _identifier = str(_args["identifier"]).strip()
        _is_addgene = _args.get("is_addgene")
        if _is_addgene is None:
            _is_addgene = _identifier.isdigit()

        if _is_addgene:
            _page_url = f"https://www.addgene.org/{_identifier}/sequences/"
            _resp = requests.get(
                _page_url, timeout=30, headers={"User-Agent": "OpenScientific-Workbench/1.0"}
            )
            _resp.raise_for_status()
            _soup = BeautifulSoup(_resp.text, "html.parser")
            _link = None
            for _a in _soup.find_all("a", href=True):
                _href = _a["href"]
                if _href.lower().endswith(".gb") or "addgene-plasmid" in _href.lower():
                    _link = _href
                    break
            if _link is None:
                raise ValueError(
                    "Could not find a downloadable GenBank sequence link on the Addgene "
                    f"sequences page for plasmid {_identifier}; the page layout may have changed."
                )
            if _link.startswith("/"):
                _link = "https://www.addgene.org" + _link
            _seq_resp = requests.get(_link, timeout=30)
            _seq_resp.raise_for_status()
            _record = SeqIO.read(io.StringIO(_seq_resp.text), "genbank")
            _result = {
                "identifier": _identifier,
                "source": "addgene",
                "name": _record.id,
                "sequence": str(_record.seq),
                "length": len(_record.seq),
            }
        else:
            Entrez.email = "anonymous@openscientific-workbench.local"
            _handle = Entrez.efetch(db="nucleotide", id=_identifier, rettype="gb", retmode="text")
            _record = SeqIO.read(_handle, "genbank")
            _handle.close()
            _result = {
                "identifier": _identifier,
                "source": "ncbi",
                "name": _record.id,
                "sequence": str(_record.seq),
                "length": len(_record.seq),
            }

        print(_json.dumps(_result))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def align_sequences(arguments: dict, driver) -> dict:
    """Aligns each of ``short_seqs`` (primers/oligos) against ``long_seq``,
    allowing at most 1 mismatch, scanning both the forward strand and the
    reverse complement. Tier A -- deterministic sliding-window
    Hamming-distance scan (`Bio.Seq.Seq.reverse_complement`).
    """
    args = AlignSequencesArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq

        _long_seq = _args["long_seq"].upper()
        _short_seqs = _args["short_seqs"]
        if isinstance(_short_seqs, str):
            _short_seqs = [_short_seqs]

        def _hamming_at_most_1(a, b):
            mismatches = sum(1 for x, y in zip(a, b) if x != y)
            return mismatches if mismatches <= 1 else None

        _alignments = []
        for _short in _short_seqs:
            _short_u = _short.upper()
            _rc = str(Seq(_short_u).reverse_complement())
            _matches = []
            _L = len(_short_u)
            for _i in range(len(_long_seq) - _L + 1):
                _window = _long_seq[_i:_i + _L]
                _mm = _hamming_at_most_1(_window, _short_u)
                if _mm is not None:
                    _matches.append({"start": _i, "end": _i + _L, "strand": "+", "mismatches": _mm})
                _mm_rc = _hamming_at_most_1(_window, _rc)
                if _mm_rc is not None:
                    _matches.append({"start": _i, "end": _i + _L, "strand": "-", "mismatches": _mm_rc})
            _alignments.append({"query": _short, "matches": _matches, "num_matches": len(_matches)})

        print(_json.dumps({"alignments": _alignments}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def pcr_simple(arguments: dict, driver) -> dict:
    """Simulates single-primer-pair PCR amplification: locates the forward
    primer's exact binding site on the + strand and the reverse primer's
    exact binding site (its reverse complement on the + strand), and returns
    the amplicon between them. Tier A -- deterministic string search;
    ``circular`` extends the search window to cover origin-spanning
    amplicons.
    """
    args = PcrSimpleArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq

        _sequence = _args["sequence"].upper()
        _fwd = _args["forward_primer"].upper()
        _rev = _args["reverse_primer"].upper()
        _circular = _args.get("circular", False)

        _search_seq = _sequence
        if _circular:
            _search_seq = _sequence + _sequence[:max(len(_fwd), len(_rev))]

        _fwd_idx = _search_seq.find(_fwd)
        if _fwd_idx == -1:
            raise ValueError("Forward primer binding site not found in the template sequence.")

        _rev_rc = str(Seq(_rev).reverse_complement())
        _rev_idx = _search_seq.find(_rev_rc, _fwd_idx)
        if _rev_idx == -1:
            raise ValueError("Reverse primer binding site not found downstream of the forward primer.")

        _amplicon_end = _rev_idx + len(_rev_rc)
        _amplicon = _search_seq[_fwd_idx:_amplicon_end]

        print(_json.dumps({
            "amplicon": _amplicon,
            "length": len(_amplicon),
            "forward_start": _fwd_idx,
            "reverse_end": _amplicon_end,
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def pcr_complex_multi_primers(arguments: dict, driver) -> dict:
    """Simulates multiplex PCR: finds every exact binding site (both
    strands) for each of ``primers`` against ``sequence``, then reports
    every valid forward/reverse binding-site combination as a candidate
    amplicon. Tier A -- deterministic combinatorial string search, the same
    primer-finding primitive as `pcr_simple` extended to N primers x all
    pairings.
    """
    args = PcrComplexMultiPrimersArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq

        _sequence = _args["sequence"].upper()
        _primers = _args["primers"]
        _circular = _args.get("circular", True)

        _pad = max((len(p) for p in _primers), default=0)
        _search_seq = _sequence + _sequence[:_pad] if _circular else _sequence

        def _find_all(haystack, needle):
            positions = []
            start = 0
            while True:
                idx = haystack.find(needle, start)
                if idx == -1:
                    break
                positions.append(idx)
                start = idx + 1
            return positions

        _sites = []
        for _idx, _p in enumerate(_primers):
            _p_u = _p.upper()
            _rc = str(Seq(_p_u).reverse_complement())
            for _pos in _find_all(_search_seq, _p_u):
                _sites.append(
                    {"primer_index": _idx, "primer": _p, "strand": "+", "start": _pos, "end": _pos + len(_p_u)}
                )
            for _pos in _find_all(_search_seq, _rc):
                _sites.append(
                    {"primer_index": _idx, "primer": _p, "strand": "-", "start": _pos, "end": _pos + len(_p_u)}
                )

        _max_len = len(_sequence)
        _products = []
        for _f in [s for s in _sites if s["strand"] == "+"]:
            for _r in [s for s in _sites if s["strand"] == "-" and s["end"] > _f["start"]]:
                _amp_len = _r["end"] - _f["start"]
                if _amp_len <= 0 or _amp_len > _max_len:
                    continue
                _products.append({
                    "forward_primer_index": _f["primer_index"],
                    "reverse_primer_index": _r["primer_index"],
                    "start": _f["start"],
                    "end": _r["end"],
                    "length": _amp_len,
                    "amplicon": _search_seq[_f["start"]:_r["end"]],
                })

        print(_json.dumps({"binding_sites": _sites, "products": _products, "num_products": len(_products)}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def digest_sequence(arguments: dict, driver) -> dict:
    """Simulates a restriction digest with a real `Bio.Restriction`
    `Analysis`, returning both the cut positions per enzyme and the
    resulting fragments (sequence + length). Tier A -- real recognition-site
    search, not a fabricated fragment list.
    """
    args = DigestSequenceArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Restriction import Analysis, RestrictionBatch
        from Bio.Seq import Seq

        _seq = Seq(_args["dna_sequence"].upper())
        _is_circular = _args.get("is_circular", True)
        _rb = RestrictionBatch(_args["enzyme_names"])
        _sites = Analysis(_rb, _seq, linear=not _is_circular).full()

        _cut_sites = {str(enz): [int(p) for p in sorted(positions)] for enz, positions in _sites.items()}
        _all_cuts = sorted({int(p) for positions in _sites.values() for p in positions})

        _fragments = []
        if not _all_cuts:
            _fragments.append({"start": 0, "end": len(_seq), "length": len(_seq), "sequence": str(_seq)})
        elif _is_circular:
            _n = len(_all_cuts)
            for _i in range(_n):
                _start = _all_cuts[_i] - 1
                _end = _all_cuts[(_i + 1) % _n] - 1
                if _end > _start:
                    _frag_seq = str(_seq[_start:_end])
                else:
                    _frag_seq = str(_seq[_start:] + _seq[:_end])
                _fragments.append({"start": _start, "end": _end, "length": len(_frag_seq), "sequence": _frag_seq})
        else:
            _boundaries = [0] + [c - 1 for c in _all_cuts] + [len(_seq)]
            for _i in range(len(_boundaries) - 1):
                _start, _end = _boundaries[_i], _boundaries[_i + 1]
                if _end <= _start:
                    continue
                _fragments.append(
                    {"start": _start, "end": _end, "length": _end - _start, "sequence": str(_seq[_start:_end])}
                )

        print(_json.dumps({"fragments": _fragments, "num_fragments": len(_fragments), "cut_sites": _cut_sites}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def golden_gate(arguments: dict, driver) -> dict:
    """Simulates a Golden Gate assembly: digests each input fragment with
    the named Type IIS enzyme (BsaI/BbsI/BtgZI/BsmBI/...) via a real
    `Bio.Restriction` `.catalyse()` call (respecting each fragment's
    ``circular`` flag), keeps only the resulting pieces that no longer
    contain the enzyme's own recognition site (the hallmark of a correctly
    designed Golden Gate reaction -- everything else is a discarded
    stuffer/flanking piece), then greedily chains those pieces into a single
    circular product by matching each piece's terminal
    ``enzyme.ovhg``-length overhang against the next piece's leading
    overhang. Tier A -- real enzyme digestion; the chaining step is a
    documented greedy simplification (assumes the enzyme-site-free pieces
    have a single unambiguous assembly order via unique overhangs, which is
    how Golden Gate is designed to work -- it does not search every
    permutation for ambiguous/degenerate overhang sets).
    """
    args = GoldenGateArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        import Bio.Restriction as _Restriction
        from Bio.Seq import Seq

        _enzyme_name = _args["enzyme_name"]
        try:
            _enzyme = getattr(_Restriction, _enzyme_name)
        except AttributeError:
            raise ValueError(f"Unknown restriction enzyme: {_enzyme_name!r}")

        _fragments = _args["fragments"]
        _circular_flags = _args["circular"]
        if len(_fragments) != len(_circular_flags):
            raise ValueError("'fragments' and 'circular' must be the same length (one flag per fragment).")

        _ovhg = abs(_enzyme.ovhg) if _enzyme.ovhg else 4

        _pieces = []
        for _frag, _is_circ in zip(_fragments, _circular_flags):
            if "sequence" not in _frag:
                raise ValueError("Each 'fragments' entry must include a 'sequence' key.")
            _seq_obj = Seq(_frag["sequence"].upper())
            for _piece in _enzyme.catalyse(_seq_obj, linear=not _is_circ):
                _pieces.append({"source": _frag.get("name"), "sequence": str(_piece)})

        _usable = []
        _discarded = []
        for _p in _pieces:
            if _enzyme.search(Seq(_p["sequence"]), linear=True):
                _discarded.append(_p)
            else:
                _usable.append(_p)

        if len(_usable) < 2:
            raise ValueError(
                f"Fewer than 2 enzyme-site-free fragments after {_enzyme_name} digestion; "
                "cannot assemble a Golden Gate product."
            )

        _chain = [_usable[0]]
        _used = {0}
        while len(_used) < len(_usable):
            _current_end = _chain[-1]["sequence"][-_ovhg:]
            _next_idx = None
            for _i, _p in enumerate(_usable):
                if _i in _used:
                    continue
                if _p["sequence"][:_ovhg] == _current_end:
                    _next_idx = _i
                    break
            if _next_idx is None:
                break
            _chain.append(_usable[_next_idx])
            _used.add(_next_idx)

        _assembled = _chain[0]["sequence"]
        for _piece in _chain[1:]:
            _assembled += _piece["sequence"][_ovhg:]
        _closes = len(_chain) == len(_usable) and _assembled[-_ovhg:] == _chain[0]["sequence"][:_ovhg]
        if _closes:
            _assembled = _assembled[:-_ovhg]

        print(_json.dumps({
            "assembled_sequence": _assembled,
            "length": len(_assembled),
            "is_circular": _closes,
            "num_pieces_used": len(_chain),
            "num_pieces_total": len(_usable),
            "discarded_pieces": _discarded,
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def oligo_assembly(arguments: dict, driver) -> dict:
    """Assembles two single-stranded oligo sequences into a duplex,
    detecting the overhang type/length by finding the offset that maximizes
    complementary base-pairing between ``seq1`` and the reverse complement
    of ``seq2`` (the correct representation of two annealed oligo strands)
    and reporting whatever unpaired 5'/3' flanking bases remain as the
    overhang. Tier A -- deterministic best-offset alignment; documented
    O(n*m) brute force (fine for oligo-length inputs).
    """
    args = OligoAssemblyArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq

        _seq1 = _args["seq1"].upper()
        _seq2 = _args["seq2"].upper()
        _rc2 = str(Seq(_seq2).reverse_complement())

        _best = None
        for _offset in range(-len(_rc2) + 1, len(_seq1)):
            _matches = 0
            _total = 0
            _lo = min(0, _offset)
            _hi = max(len(_seq1), _offset + len(_rc2))
            for _i in range(_lo, _hi):
                _c1 = _seq1[_i] if 0 <= _i < len(_seq1) else None
                _c2 = _rc2[_i - _offset] if 0 <= _i - _offset < len(_rc2) else None
                if _c1 is not None and _c2 is not None:
                    _total += 1
                    if _c1 == _c2:
                        _matches += 1
            if _total == 0:
                continue
            _score = _matches - (_total - _matches) * 2
            if _best is None or _score > _best[0]:
                _best = (_score, _offset, _matches, _total)

        if _best is None:
            raise ValueError("seq1/seq2 have no overlapping region to align.")

        _score, _offset, _matches, _total = _best
        _duplex_start = max(0, _offset)
        _duplex_end = min(len(_seq1), _offset + len(_rc2))

        _overhang_5p = _seq1[:_duplex_start] if _duplex_start > 0 else (_rc2[:-_offset] if _offset < 0 else "")
        _rc2_tail_idx = _duplex_end - _offset
        _overhang_3p = (
            _seq1[_duplex_end:] if _duplex_end < len(_seq1)
            else (_rc2[_rc2_tail_idx:] if _rc2_tail_idx < len(_rc2) else "")
        )

        if _overhang_5p and _overhang_3p:
            _overhang_type = "both"
        elif _overhang_5p:
            _overhang_type = "5_overhang"
        elif _overhang_3p:
            _overhang_type = "3_overhang"
        else:
            _overhang_type = "blunt"

        print(_json.dumps({
            "duplex_region": _seq1[_duplex_start:_duplex_end],
            "duplex_length": _duplex_end - _duplex_start,
            "overhang_5prime": _overhang_5p,
            "overhang_3prime": _overhang_3p,
            "overhang_type": _overhang_type,
            "overhang_length": max(len(_overhang_5p), len(_overhang_3p)),
            "mismatches_in_duplex": _total - _matches,
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def gibson_assembly(arguments: dict, driver) -> dict:
    """Simulates Gibson Assembly: greedily chains ``fragments`` (trying both
    orientations of each, since Gibson-assembled parts are supplied without
    a fixed strand convention) by matching exact overlapping ends of at
    least ``min_overlap`` bases, merging each match's shared overlap once,
    and closing the chain into a circle when the last piece's end overlaps
    the first piece's start. Tier A -- deterministic overlap-layout
    chaining; documented greedy simplification (picks the best next overlap
    at each step rather than exhaustively searching every fragment
    ordering, which is combinatorially explosive for many fragments).
    """
    args = GibsonAssemblyArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq

        _fragments = _args["fragments"]
        _min_overlap = _args.get("min_overlap", 15)

        def _best_overlap(a, b, min_overlap):
            max_ov = min(len(a), len(b))
            for ov in range(max_ov, min_overlap - 1, -1):
                if ov > 0 and a[-ov:] == b[:ov]:
                    return ov
            return 0

        _oriented = []
        for _i, _f in enumerate(_fragments):
            _f_u = _f.upper()
            _oriented.append({"index": _i, "orientation": "+", "sequence": _f_u})
            _oriented.append({"index": _i, "orientation": "-", "sequence": str(Seq(_f_u).reverse_complement())})

        _used = {0}
        _chain = [_oriented[0]]
        _current = _oriented[0]
        while len(_used) < len(_fragments):
            _best = None
            for _cand in _oriented:
                if _cand["index"] in _used:
                    continue
                _ov = _best_overlap(_current["sequence"], _cand["sequence"], _min_overlap)
                if _ov > 0 and (_best is None or _ov > _best[0]):
                    _best = (_ov, _cand)
            if _best is None:
                break
            _ov, _cand = _best
            _chain.append({**_cand, "overlap_with_prev": _ov})
            _used.add(_cand["index"])
            _current = _cand

        _assembled = _chain[0]["sequence"]
        for _piece in _chain[1:]:
            _assembled += _piece["sequence"][_piece["overlap_with_prev"]:]

        _closing_overlap = _best_overlap(_assembled, _chain[0]["sequence"], _min_overlap)
        _is_circular = _closing_overlap > 0
        if _is_circular:
            _assembled = _assembled[:-_closing_overlap]

        _result = {
            "assembled_sequence": _assembled,
            "length": len(_assembled),
            "is_circular": _is_circular,
            "fragment_order": [{"fragment_index": c["index"], "orientation": c["orientation"]} for c in _chain],
            "num_fragments_used": len(_used),
            "num_fragments_input": len(_fragments),
        }
        if len(_used) < len(_fragments):
            _result["warning"] = "Not all fragments could be chained with an overlap >= min_overlap."
        print(_json.dumps(_result))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def find_restriction_sites(arguments: dict, driver) -> dict:
    """Identifies recognition sites/cut positions for a caller-specified
    list of restriction enzymes (real `Bio.Restriction` search, one enzyme
    at a time so an unknown enzyme name is reported per-enzyme rather than
    failing the whole batch). Tier A.
    """
    args = FindRestrictionSitesArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        import Bio.Restriction as _Restriction
        from Bio.Seq import Seq

        _seq = Seq(_args["dna_sequence"].upper())
        _is_circular = _args.get("is_circular", True)

        _sites = {}
        for _name in _args["enzymes"]:
            try:
                _enzyme = getattr(_Restriction, _name)
            except AttributeError:
                _sites[_name] = {"error": f"Unknown restriction enzyme: {_name!r}"}
                continue
            _positions = _enzyme.search(_seq, linear=not _is_circular)
            _sites[_name] = {
                "recognition_site": str(_enzyme.site),
                "cut_positions": [int(p) for p in _positions],
                "num_sites": len(_positions),
            }

        print(_json.dumps({"sites": _sites}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def find_restriction_enzymes(arguments: dict, driver) -> dict:
    """Scans ``sequence`` against Biopython's real `CommOnly` restriction
    enzyme battery (commercially available enzymes) and returns every
    enzyme with at least one cut site, plus its cut positions. Tier A.
    """
    args = FindRestrictionEnzymesArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Restriction import CommOnly
        from Bio.Seq import Seq

        _seq = Seq(_args["sequence"].upper())
        _is_circular = _args.get("is_circular", False)

        _found = {}
        for _enzyme in CommOnly:
            _positions = _enzyme.search(_seq, linear=not _is_circular)
            if _positions:
                _found[str(_enzyme)] = [int(p) for p in _positions]

        print(_json.dumps({"enzymes_found": _found, "num_enzymes_with_sites": len(_found)}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def design_primers_with_overhangs(arguments: dict, driver) -> dict:
    """Designs a forward/reverse primer pair for ``sequence``, prepending
    the given overhangs, extending each primer's annealing region from
    ``min_primer_length`` until its real nearest-neighbor melting
    temperature (`Bio.SeqUtils.MeltingTemp.Tm_NN`) reaches ``target_tm`` (or
    the closest achievable Tm within a 60 nt cap). Tier A.
    """
    args = DesignPrimersWithOverhangsArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq
        from Bio.SeqUtils import MeltingTemp as _mt

        _sequence = _args["sequence"].upper()
        _fwd_oh = _args["forward_overhang"].upper()
        _rev_oh = _args["reverse_overhang"].upper()
        _target_tm = _args["target_tm"]
        _min_len = _args.get("min_primer_length", 15)

        def _extend_to_tm(source, min_len, target_tm, max_len=60):
            best = None
            for length in range(min_len, min(max_len, len(source)) + 1):
                anneal = source[:length]
                tm = _mt.Tm_NN(anneal)
                if best is None or abs(tm - target_tm) < abs(best[1] - target_tm):
                    best = (anneal, tm, length)
                if tm >= target_tm:
                    break
            return best

        _fwd_best = _extend_to_tm(_sequence, _min_len, _target_tm)
        if _fwd_best is None:
            raise ValueError("Sequence too short to design a forward primer of the requested minimum length.")
        _fwd_anneal, _fwd_tm, _ = _fwd_best

        _rc = str(Seq(_sequence).reverse_complement())
        _rev_best = _extend_to_tm(_rc, _min_len, _target_tm)
        if _rev_best is None:
            raise ValueError("Sequence too short to design a reverse primer of the requested minimum length.")
        _rev_anneal, _rev_tm, _ = _rev_best

        print(_json.dumps({
            "forward_primer": _fwd_oh + _fwd_anneal,
            "forward_annealing_region": _fwd_anneal,
            "forward_tm": round(_fwd_tm, 2),
            "reverse_primer": _rev_oh + _rev_anneal,
            "reverse_annealing_region": _rev_anneal,
            "reverse_tm": round(_rev_tm, 2),
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def find_sequence_mutations(arguments: dict, driver) -> dict:
    """Compares ``query_sequence`` against ``reference_sequence`` position
    by position, starting at 1-based ``query_start`` in the reference, and
    reports every mismatched base as a point mutation (``ref_base + pos +
    query_base`` notation). Tier A. Documented limitation: this is a direct
    1:1 positional comparison, not an indel-aware alignment -- sequences
    that may contain insertions/deletions should be aligned first (e.g. via
    `align_sequences`) before comparing.
    """
    args = FindSequenceMutationsArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        _query = _args["query_sequence"].upper()
        _reference = _args["reference_sequence"].upper()
        _query_start = _args.get("query_start", 1)

        _mutations = []
        for _i, _q_base in enumerate(_query):
            _ref_pos = _query_start + _i
            _ref_idx = _ref_pos - 1
            if _ref_idx < 0 or _ref_idx >= len(_reference):
                continue
            _ref_base = _reference[_ref_idx]
            if _q_base != _ref_base:
                _mutations.append({
                    "position": _ref_pos,
                    "reference_base": _ref_base,
                    "query_base": _q_base,
                    "mutation": f"{_ref_base}{_ref_pos}{_q_base}",
                })

        print(_json.dumps({
            "mutations": _mutations,
            "num_mutations": len(_mutations),
            "query_length": len(_query),
            "reference_length": len(_reference),
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def get_molecular_cloning_instructions(arguments: dict, driver) -> dict:
    """Returns a static reference dict of molecular-cloning/plasmid-
    circularity guidance (numbering conventions, ori copy-number families,
    common selection markers). Tier A -- genuinely useful reference text,
    not simulated data; still routed through the sandbox for uniformity
    with every other action tool. No arguments.
    """
    _NoArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        _instructions = {
            "plasmid_numbering": (
                "Circular plasmid coordinates are conventionally 1-based and reported relative "
                "to a defined origin (often the first base of a chosen restriction site or the "
                "start of the ori); position 1 immediately follows the highest numbered base "
                "when wrapping around the origin."
            ),
            "circularity_handling": (
                "When simulating digests/PCR/assembly on a circular construct, treat the "
                "sequence as wrapping: a fragment or amplicon may span the origin, and cut "
                "sites/binding sites must be searched across the origin junction, not just "
                "within the linear string as given."
            ),
            "ori_copy_number_families": {
                "pUC/pMB1 (high copy)": "~500-700 copies/cell, e.g. pUC19, pUC57.",
                "ColE1/pBR322 (medium copy)": "~15-20 copies/cell, e.g. pBR322 derivatives.",
                "p15A (low-medium, compatible with ColE1)": "~10-12 copies/cell.",
                "pSC101 (low copy)": "~5 copies/cell, useful for toxic-gene expression.",
            },
            "common_selection_markers": {
                "AmpR (bla)": "beta-lactamase, ampicillin/carbenicillin resistance.",
                "KanR": "aminoglycoside phosphotransferase, kanamycin resistance.",
                "CmR (cat)": "chloramphenicol acetyltransferase.",
                "SpecR (aadA)": "spectinomycin/streptomycin resistance.",
            },
            "general_advice": [
                "Always verify a final construct by Sanger sequencing across every junction "
                "created during assembly, not just the insert.",
                "Prefer enzymes/overhangs that leave no scar sequence when the application "
                "requires seamless fusion (Gibson/Golden Gate over classic sticky-end ligation).",
                "Check for internal recognition sites of the assembly enzyme within the insert "
                "before choosing it (Type IIS enzymes especially -- an off-target internal site "
                "will fragment the insert during assembly).",
            ],
        }
        print(_json.dumps(_instructions))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args={})


def calculate_element_distances(arguments: dict, driver) -> dict:
    """Computes pairwise spacing between annotated elements on a plasmid
    (each ``element_positions`` entry: ``{"name": str, "start": int, "end":
    int}``, 0-based half-open). For every unordered pair, reports the
    forward gap (lower-start element's end to higher-start element's start)
    and, when ``is_circular``, the wraparound gap the other way around the
    plasmid. Tier A -- deterministic arithmetic.
    """
    args = CalculateElementDistancesArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        _seq_len = _args["sequence_length"]
        _elements = list(_args["element_positions"])
        _is_circular = _args.get("is_circular", True)

        _order = sorted(range(len(_elements)), key=lambda i: _elements[i]["start"])
        _distances = []
        for _pi in range(len(_order)):
            for _pj in range(_pi + 1, len(_order)):
                _a = _elements[_order[_pi]]
                _b = _elements[_order[_pj]]
                _gap_forward = _b["start"] - _a["end"]
                _entry = {
                    "element_a": _a.get("name") or _order[_pi],
                    "element_b": _b.get("name") or _order[_pj],
                    "gap_bp": _gap_forward,
                }
                if _is_circular:
                    _entry["wraparound_gap_bp"] = _seq_len - _b["end"] + _a["start"]
                    _entry["shortest_gap_bp"] = min(_gap_forward, _entry["wraparound_gap_bp"])
                _distances.append(_entry)

        print(_json.dumps({"distances": _distances, "num_pairs": len(_distances)}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def design_knockout_sgrna(arguments: dict, driver) -> dict:
    """Looks up pre-validated knockout sgRNA guides for ``gene_name`` from a
    bundled, pre-computed per-species library in the data lake
    (``/datalake/sgrna_library_<species>.csv``, columns at least ``gene``,
    ``guide_sequence``, ``score``), returning the top ``num_guides`` by
    score. Tier A -- real library lookup, NEVER a fabricated guide sequence:
    if the library file is missing from the data lake (true as of this
    writing -- `data_lake/MANIFEST.md` has no sgRNA-library entry yet) or
    has no rows for the requested gene, this fails loudly with a message
    naming `backend/scripts/fetch_data_lake.py` instead of inventing a
    guide, exactly as `action_tool_catalog.md` specifies for this tool.
    """
    args = DesignKnockoutSgrnaArgs.model_validate(arguments or {})
    # `species` is used to build a data-lake filename inside the sandboxed
    # script below -- guard it exactly like any other file-path-shaped
    # argument (`ensure_safe_relative_path`, `domain/services/path_guard.py`)
    # before it ever leaves this trusted handler, so e.g.
    # species="../../etc/passwd" can never be used to read outside
    # `/datalake`.
    species_token = ensure_safe_relative_path(args.species.strip().lower())
    if "/" in species_token:
        raise PathTraversalError(
            f"'species' must be a single path segment, not a path: {args.species!r}"
        )
    script_body = textwrap.dedent(
        """
        import csv
        import os

        _lib_path = "/datalake/sgrna_library_" + _args["species_token"] + ".csv"
        if not os.path.exists(_lib_path):
            raise FileNotFoundError(
                "Pre-computed sgRNA guide library not found at " + _lib_path + ". "
                "This tool only ever returns real, pre-validated guides from a bundled "
                "library and never fabricates a guide sequence. Populate the data lake "
                "(see backend/scripts/fetch_data_lake.py and data_lake/MANIFEST.md) with "
                "a matching 'sgrna_library_<species>.csv' file, or add one manually to "
                "the data_lake/ directory, then retry."
            )

        _gene_name = _args["gene_name"]
        _num_guides = _args.get("num_guides", 1)
        _guides = []
        with open(_lib_path, newline="", encoding="utf-8") as _fh:
            for _row in csv.DictReader(_fh):
                if _row.get("gene", "").strip().upper() == _gene_name.strip().upper():
                    _guides.append(_row)

        if not _guides:
            raise ValueError(f"No sgRNA guides found for gene {_gene_name!r} in {_lib_path}.")

        _guides.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)
        _top = _guides[:_num_guides]

        print(_json.dumps({
            "gene_name": _gene_name,
            "species": _args["species"],
            "guides": _top,
            "num_guides": len(_top),
        }))
        """
    ).strip()
    validated = args.model_dump()
    validated["species_token"] = species_token
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def design_golden_gate_oligos(arguments: dict, driver) -> dict:
    """Designs insert-amplification oligos with Type IIS overhangs matching
    ``backbone_sequence``'s own overhangs after digestion with
    ``enzyme_name``: digests the backbone (real `Bio.Restriction.catalyse`,
    respecting ``is_circular``), takes the largest resulting fragment as the
    retained vector piece, reads its 5'/3' terminal ``ovhg``-length
    overhangs, and prepends ``[recognition site][1 nt spacer][overhang]`` to
    an 18 nt annealing region on each end of ``insert_sequence``. Tier A --
    real digestion + a documented standard Golden Gate oligo-design
    convention (1 nt spacer, 18 nt annealing length are common defaults, not
    fabricated numbers -- a caller wanting different values should design
    manually).
    """
    args = DesignGoldenGateOligosArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        import Bio.Restriction as _Restriction
        from Bio.Seq import Seq

        _enzyme_name = _args.get("enzyme_name", "BsmBI")
        try:
            _enzyme = getattr(_Restriction, _enzyme_name)
        except AttributeError:
            raise ValueError(f"Unknown restriction enzyme: {_enzyme_name!r}")

        _insert_seq = _args["insert_sequence"].upper()
        _backbone_seq = _args["backbone_sequence"].upper()
        _is_circular = _args.get("is_circular", True)
        _anneal_len = 18

        _backbone = Seq(_backbone_seq)
        _frags = _enzyme.catalyse(_backbone, linear=not _is_circular)
        if len(_frags) < 2:
            raise ValueError(
                f"{_enzyme_name} does not cut the backbone at >= 2 sites; cannot determine "
                "Golden Gate overhangs."
            )

        _vector_fragment = str(max(_frags, key=len))
        _ovhg = abs(_enzyme.ovhg) if _enzyme.ovhg else 4
        _five_overhang = _vector_fragment[:_ovhg]
        _three_overhang = _vector_fragment[-_ovhg:]
        _site = str(_enzyme.site)
        _spacer = "N"

        _forward_oligo = _site + _spacer + _five_overhang + _insert_seq[:_anneal_len]
        _insert_rc = str(Seq(_insert_seq).reverse_complement())
        _three_overhang_rc = str(Seq(_three_overhang).reverse_complement())
        _reverse_oligo = _site + _spacer + _three_overhang_rc + _insert_rc[:_anneal_len]

        print(_json.dumps({
            "enzyme": _enzyme_name,
            "recognition_site": _site,
            "overhang_length": _ovhg,
            "backbone_5prime_overhang": _five_overhang,
            "backbone_3prime_overhang": _three_overhang,
            "forward_oligo": _forward_oligo,
            "reverse_oligo": _reverse_oligo,
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def get_oligo_annealing_protocol(arguments: dict, driver) -> dict:
    """Returns the standard oligo-annealing protocol (no 5' phosphorylation
    step). Tier A -- static reference text, routed through the sandbox for
    uniformity. No arguments.
    """
    _NoArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        _protocol = {
            "name": "Standard oligo annealing (no phosphorylation)",
            "reagents": {
                "forward_oligo_100uM": "1 uL",
                "reverse_oligo_100uM": "1 uL",
                "10x_annealing_buffer": "5 uL (100 mM Tris-HCl pH 7.5-8.0, 500 mM NaCl or 10 mM MgCl2/1M NaCl)",
                "water": "43 uL (to 50 uL total)",
            },
            "steps": [
                "Combine equimolar forward and reverse oligos (final ~2 uM each) in 1x annealing buffer.",
                "Heat to 95C for 2-5 min in a thermocycler or heat block.",
                "Turn off the heat block, or let the thermocycler ramp down slowly to room "
                "temperature (~0.1C/sec, ~45-90 min) to allow gradual, specific annealing.",
                "Store the annealed duplex at -20C, or dilute for direct use in ligation.",
            ],
            "notes": (
                "No T4 PNK phosphorylation step is included; if the destination vector is not "
                "already dephosphorylated/blunt-compatible for 5' ligation, phosphorylate the "
                "oligos with T4 PNK + ATP before annealing instead."
            ),
        }
        print(_json.dumps(_protocol))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args={})


def get_golden_gate_assembly_protocol(arguments: dict, driver) -> dict:
    """Builds a customized Golden Gate assembly protocol/reaction recipe:
    per-insert molar amounts from standard NEB molar-ratio guidance
    (insert:vector ~2:1 for a normal assembly, ~5:1 when
    ``is_library_prep`` favors multi-insert coverage), computed with the
    standard ``insert_ng = vector_ng * (insert_len/vector_len) *
    molar_ratio`` ligation-molar-ratio formula, plus NEB's published Golden
    Gate digestion-ligation thermocycler protocol. Tier A -- real,
    documented formula + a real published cycling protocol, not fabricated
    numbers.
    """
    args = GetGoldenGateAssemblyProtocolArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        _enzyme_name = _args["enzyme_name"]
        _vector_length = _args["vector_length"]
        _num_inserts = _args.get("num_inserts", 1)
        _vector_amount_ng = _args.get("vector_amount_ng", 75.0)
        _insert_lengths = _args.get("insert_lengths")
        _is_library_prep = _args.get("is_library_prep", False)

        if _insert_lengths is None:
            _insert_lengths = [max(1, _vector_length // 4)] * _num_inserts

        _molar_ratio = 5 if _is_library_prep else 2

        _insert_amounts = []
        for _length in _insert_lengths:
            _ng = _vector_amount_ng * (_length / _vector_length) * _molar_ratio
            _insert_amounts.append({"insert_length_bp": _length, "insert_amount_ng": round(_ng, 2)})

        _protocol = {
            "enzyme": _enzyme_name,
            "vector_amount_ng": _vector_amount_ng,
            "vector_length_bp": _vector_length,
            "molar_ratio_insert_to_vector": _molar_ratio,
            "insert_amounts": _insert_amounts,
            "reaction_recipe": {
                "vector": f"{_vector_amount_ng} ng",
                "inserts_ng": [a["insert_amount_ng"] for a in _insert_amounts],
                _enzyme_name: "1 uL (per manufacturer's recommended units, e.g. NEB Golden Gate Assembly Mix)",
                "t4_dna_ligase_buffer_10x": "2 uL",
                "water": "to 20 uL total",
            },
            "thermocycler_protocol": [
                {"step": "digestion-ligation cycling", "cycles": 30, "temp_c": 37, "time_sec": 60},
                {"step": "digestion-ligation cycling", "cycles": 30, "temp_c": 16, "time_sec": 60},
                {"step": "final digestion", "temp_c": 37, "time_min": 5},
                {"step": "enzyme heat inactivation", "temp_c": 60, "time_min": 5},
            ],
            "notes": (
                "Molar-ratio guidance follows NEB's standard Golden Gate Assembly recommendations "
                "(1:2 vector:insert per insert normally, 1:5 for pooled library prep to favor "
                "multi-insert products)."
            ),
        }
        print(_json.dumps(_protocol))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def get_bacterial_transformation_protocol(arguments: dict, driver) -> dict:
    """Returns a standard heat-shock bacterial transformation protocol with
    real, textbook antibiotic selection concentrations
    (ampicillin/kanamycin/chloramphenicol/spectinomycin/streptomycin/
    tetracycline), adjusted for repeat-prone/unstable inserts when
    ``is_repetitive`` (lower 30C growth temperature, longer outgrowth, and a
    recombination-deficient strain recommendation). Tier A -- static
    reference protocol, routed through the sandbox for uniformity.
    """
    args = GetBacterialTransformationProtocolArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        _antibiotic = _args.get("antibiotic", "ampicillin").lower()
        _is_repetitive = _args.get("is_repetitive", False)

        _concentrations = {
            "ampicillin": {"working_ug_ml": 100, "stock_mg_ml": 100, "solvent": "water"},
            "kanamycin": {"working_ug_ml": 50, "stock_mg_ml": 50, "solvent": "water"},
            "chloramphenicol": {"working_ug_ml": 25, "stock_mg_ml": 25, "solvent": "ethanol"},
            "spectinomycin": {"working_ug_ml": 100, "stock_mg_ml": 100, "solvent": "water"},
            "streptomycin": {"working_ug_ml": 50, "stock_mg_ml": 50, "solvent": "water"},
            "tetracycline": {"working_ug_ml": 12.5, "stock_mg_ml": 12.5, "solvent": "ethanol"},
        }
        if _antibiotic not in _concentrations:
            raise ValueError(f"Unknown antibiotic {_antibiotic!r}. Supported: {sorted(_concentrations)}")
        _conc = _concentrations[_antibiotic]

        _outgrowth_min = 90 if _is_repetitive else 60
        _incubation_temp_c = 30 if _is_repetitive else 37

        _steps = [
            "Thaw chemically competent cells on ice (do not vortex).",
            "Add 1-5 uL (1-10 ng) of plasmid DNA to 50 uL competent cells; mix gently.",
            "Incubate on ice for 30 min.",
            "Heat-shock at 42C for 30-45 sec, then return to ice for 2 min.",
            f"Add 950 uL room-temperature SOC medium; recover by shaking at {_incubation_temp_c}C "
            f"for {_outgrowth_min} min.",
            f"Plate 50-200 uL on LB agar + {_conc['working_ug_ml']} ug/mL {_antibiotic}.",
            f"Incubate plates overnight (16-18h) at {_incubation_temp_c}C.",
        ]
        if _is_repetitive:
            _steps.append(
                "For repetitive/unstable inserts: use a recombination-deficient strain (e.g. NEB "
                "Stable) and keep growth at 30C throughout to reduce recombination/deletion risk."
            )

        print(_json.dumps({
            "antibiotic": _antibiotic,
            "selection_concentration_ug_ml": _conc["working_ug_ml"],
            "stock_solution": f"{_conc['stock_mg_ml']} mg/mL in {_conc['solvent']}, filter-sterilized, "
            "stored at -20C",
            "outgrowth_time_min": _outgrowth_min,
            "incubation_temp_c": _incubation_temp_c,
            "protocol_steps": _steps,
        }))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def design_primer(arguments: dict, driver) -> dict:
    """Designs a single primer of ``primer_length`` starting within
    ``search_window`` bases of ``start_pos``, scanning every candidate
    window for real GC-fraction (`Bio.SeqUtils.gc_fraction`) and
    nearest-neighbor Tm (`Bio.SeqUtils.MeltingTemp.Tm_NN`) constraints, and
    returning the candidate whose Tm is closest to the midpoint of
    ``[min_tm, max_tm]``. Tier A.
    """
    args = DesignPrimerArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.SeqUtils import MeltingTemp as _mt
        from Bio.SeqUtils import gc_fraction as _gc_fraction

        _sequence = _args["sequence"].upper()
        _start_pos = _args["start_pos"]
        _primer_length = _args.get("primer_length", 20)
        _min_gc = _args.get("min_gc", 0.4)
        _max_gc = _args.get("max_gc", 0.6)
        _min_tm = _args.get("min_tm", 55.0)
        _max_tm = _args.get("max_tm", 65.0)
        _search_window = _args.get("search_window", 100)

        _candidates = []
        _end_search = min(len(_sequence) - _primer_length, _start_pos + _search_window)
        for _pos in range(max(0, _start_pos), max(0, _end_search) + 1):
            _candidate = _sequence[_pos:_pos + _primer_length]
            if len(_candidate) < _primer_length:
                continue
            _gc = _gc_fraction(_candidate)
            _tm = _mt.Tm_NN(_candidate)
            if _min_gc <= _gc <= _max_gc and _min_tm <= _tm <= _max_tm:
                _candidates.append({
                    "start": _pos,
                    "end": _pos + _primer_length,
                    "sequence": _candidate,
                    "gc_fraction": round(_gc, 3),
                    "tm": round(_tm, 2),
                })

        if not _candidates:
            raise ValueError(
                f"No {_primer_length} nt primer within {_search_window} bp of position {_start_pos} "
                f"satisfies GC in [{_min_gc}, {_max_gc}] and Tm in [{_min_tm}, {_max_tm}]."
            )

        _midpoint = (_min_tm + _max_tm) / 2
        _best = min(_candidates, key=lambda c: abs(c["tm"] - _midpoint))
        print(_json.dumps({"primer": _best, "num_candidates": len(_candidates)}))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


def design_verification_primers(arguments: dict, driver) -> dict:
    """Designs Sanger-verification primers flanking ``target_region``,
    reusing any ``existing_primers`` that already give ``coverage_length``
    of Sanger-read coverage over the target before designing new ones with
    the same GC/Tm-window search `design_primer` uses. Tier A. Documented
    simplification: coverage-checking treats the plasmid as linear even when
    ``is_circular`` (a target region near the origin may need a manually
    reviewed primer) -- this mirrors `find_sequence_mutations`'s stated
    scope limits rather than silently guessing wraparound coverage.
    """
    args = DesignVerificationPrimersArgs.model_validate(arguments or {})
    script_body = textwrap.dedent(
        """
        from Bio.Seq import Seq
        from Bio.SeqUtils import MeltingTemp as _mt
        from Bio.SeqUtils import gc_fraction as _gc_fraction

        _plasmid_seq = _args["plasmid_sequence"].upper()
        _target_start, _target_end = _args["target_region"]
        _existing_primers = _args.get("existing_primers") or []
        _coverage_length = _args.get("coverage_length", 800)
        _primer_length = _args.get("primer_length", 20)
        _min_gc = _args.get("min_gc", 0.4)
        _max_gc = _args.get("max_gc", 0.6)
        _min_tm = _args.get("min_tm", 55.0)
        _max_tm = _args.get("max_tm", 65.0)

        def _covers(pos, direction, target_start, target_end, coverage_length):
            if direction == "forward":
                return pos <= target_start and (pos + coverage_length) >= target_end
            return (pos - coverage_length) <= target_start and pos >= target_end

        _reused = []
        for _p in _existing_primers:
            _pos = _p.get("position", _p.get("start"))
            _direction = _p.get("direction", "forward")
            if _pos is None:
                continue
            if _covers(_pos, _direction, _target_start, _target_end, _coverage_length):
                _reused.append(_p)

        _result = {"reused_primers": _reused}

        if not _reused:
            def _design_window(search_start, search_end):
                best = None
                for pos in range(max(0, search_start), max(0, search_end - _primer_length) + 1):
                    candidate = _plasmid_seq[pos:pos + _primer_length]
                    if len(candidate) < _primer_length:
                        continue
                    gc = _gc_fraction(candidate)
                    tm = _mt.Tm_NN(candidate)
                    if _min_gc <= gc <= _max_gc and _min_tm <= tm <= _max_tm:
                        score = abs(tm - (_min_tm + _max_tm) / 2)
                        if best is None or score < best[0]:
                            best = (score, {
                                "start": pos, "end": pos + _primer_length, "sequence": candidate,
                                "gc_fraction": round(gc, 3), "tm": round(tm, 2),
                            })
                return best[1] if best else None

            _fwd = _design_window(_target_start - _coverage_length, _target_start)
            _rev_region = _design_window(_target_end, _target_end + _coverage_length)
            _rev = None
            if _rev_region is not None:
                _rev = dict(_rev_region)
                _rev["sequence"] = str(Seq(_rev_region["sequence"]).reverse_complement())

            _result["designed_forward_primer"] = _fwd
            _result["designed_reverse_primer"] = _rev
            if _fwd is None and _rev is None:
                raise ValueError(
                    "Could not design verification primers meeting the GC/Tm constraints near "
                    "the target region."
                )

        print(_json.dumps(_result))
        """
    ).strip()
    return run_in_sandbox(driver, script_body=script_body, args=args.model_dump())


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def register_cloning_tools(registry, driver) -> List[str]:
    """Registers every molecular-cloning & DNA-engineering action tool
    (Tier A per `action_tool_catalog.md`'s "Molecular cloning & DNA
    engineering" heading -- this category has no Tier D entries) into
    `registry`, each bound to the given sandbox `driver`. Returns the
    registered tool names.
    """
    handlers = {
        "annotate_open_reading_frames": annotate_open_reading_frames,
        "annotate_plasmid": annotate_plasmid,
        "get_gene_coding_sequence": get_gene_coding_sequence,
        "get_plasmid_sequence": get_plasmid_sequence,
        "align_sequences": align_sequences,
        "pcr_simple": pcr_simple,
        "pcr_complex_multi_primers": pcr_complex_multi_primers,
        "digest_sequence": digest_sequence,
        "golden_gate": golden_gate,
        "oligo_assembly": oligo_assembly,
        "gibson_assembly": gibson_assembly,
        "find_restriction_sites": find_restriction_sites,
        "find_restriction_enzymes": find_restriction_enzymes,
        "design_primers_with_overhangs": design_primers_with_overhangs,
        "find_sequence_mutations": find_sequence_mutations,
        "get_molecular_cloning_instructions": get_molecular_cloning_instructions,
        "calculate_element_distances": calculate_element_distances,
        "design_knockout_sgrna": design_knockout_sgrna,
        "design_golden_gate_oligos": design_golden_gate_oligos,
        "get_oligo_annealing_protocol": get_oligo_annealing_protocol,
        "get_golden_gate_assembly_protocol": get_golden_gate_assembly_protocol,
        "get_bacterial_transformation_protocol": get_bacterial_transformation_protocol,
        "design_primer": design_primer,
        "design_verification_primers": design_verification_primers,
    }
    for name, handler in handlers.items():
        registry.register_server(name, functools.partial(handler, driver=driver))
    return list(handlers.keys())
