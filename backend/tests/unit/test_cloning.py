"""Unit tests for `infrastructure/tools/cloning.py` (Fase 5 molecular
cloning & DNA engineering action tools).

Per `_sandbox_tool_base.py`'s documented testing boundary (see that
module's docstring), these tests verify the WIRING and VALIDATION layer
only: Pydantic argument validation happens (and short-circuits before any
sandbox call) on bad input, valid `arguments` round-trip correctly into the
JSON `_args` file the sandboxed script would read, and a canned
`FakeSandboxDriver` result is parsed back correctly. They do NOT (cannot,
by design -- the `script_body` strings import biopython/Bio.Restriction/etc,
which only exist in the sandbox toolkit's own conda env, never in this
repo's own pytest venv) execute or assert on the real scientific logic
inside any `script_body`.
"""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.tools import cloning
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver


def _driver(stdout=None):
    driver = FakeSandboxDriver()
    if stdout is not None:
        driver.stdout = json.dumps(stdout)
    return driver


# --------------------------------------------------------------------------
# annotate_open_reading_frames
# --------------------------------------------------------------------------


def test_annotate_open_reading_frames_round_trip_and_result():
    driver = _driver({"orfs": [], "num_orfs": 0})
    result = cloning.annotate_open_reading_frames(
        {"sequence": "atgaaataa", "min_length": 6, "search_reverse": True}, driver
    )
    assert result == {"orfs": [], "num_orfs": 0}
    assert driver.last_args() == {
        "sequence": "atgaaataa",
        "min_length": 6,
        "search_reverse": True,
        "filter_subsets": False,
    }


def test_annotate_open_reading_frames_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.annotate_open_reading_frames({"sequence": "ATG"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# annotate_plasmid
# --------------------------------------------------------------------------


def test_annotate_plasmid_round_trip_and_result():
    driver = _driver({"features": [], "num_features": 0, "is_circular": True})
    result = cloning.annotate_plasmid({"sequence": "ATGC"}, driver)
    assert result == {"features": [], "num_features": 0, "is_circular": True}
    assert driver.last_args() == {"sequence": "ATGC", "is_circular": True, "return_plot": False}


def test_annotate_plasmid_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.annotate_plasmid({}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# get_gene_coding_sequence
# --------------------------------------------------------------------------


def test_get_gene_coding_sequence_round_trip_and_result():
    driver = _driver({"gene_name": "TP53", "coding_sequence": "ATG...", "length": 6})
    result = cloning.get_gene_coding_sequence(
        {"gene_name": "TP53", "organism": "Homo sapiens"}, driver
    )
    assert result == {"gene_name": "TP53", "coding_sequence": "ATG...", "length": 6}
    assert driver.last_args() == {"gene_name": "TP53", "organism": "Homo sapiens", "email": None}


def test_get_gene_coding_sequence_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.get_gene_coding_sequence({"gene_name": "TP53"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# get_plasmid_sequence
# --------------------------------------------------------------------------


def test_get_plasmid_sequence_round_trip_and_result():
    driver = _driver({"identifier": "12345", "source": "addgene", "sequence": "ACGT", "length": 4})
    result = cloning.get_plasmid_sequence({"identifier": "12345"}, driver)
    assert result["source"] == "addgene"
    assert driver.last_args() == {"identifier": "12345", "is_addgene": None}


def test_get_plasmid_sequence_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.get_plasmid_sequence({}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# align_sequences
# --------------------------------------------------------------------------


def test_align_sequences_round_trip_and_result():
    driver = _driver({"alignments": []})
    result = cloning.align_sequences(
        {"long_seq": "ACGTACGT", "short_seqs": ["ACGT", "CGTA"]}, driver
    )
    assert result == {"alignments": []}
    assert driver.last_args() == {"long_seq": "ACGTACGT", "short_seqs": ["ACGT", "CGTA"]}


def test_align_sequences_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.align_sequences({"long_seq": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# pcr_simple
# --------------------------------------------------------------------------


def test_pcr_simple_round_trip_and_result():
    driver = _driver({"amplicon": "ACGT", "length": 4, "forward_start": 0, "reverse_end": 4})
    result = cloning.pcr_simple(
        {"sequence": "ACGT", "forward_primer": "AC", "reverse_primer": "GT"}, driver
    )
    assert result["length"] == 4
    assert driver.last_args() == {
        "sequence": "ACGT",
        "forward_primer": "AC",
        "reverse_primer": "GT",
        "circular": False,
    }


def test_pcr_simple_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.pcr_simple({"sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# pcr_complex_multi_primers
# --------------------------------------------------------------------------


def test_pcr_complex_multi_primers_round_trip_and_result():
    driver = _driver({"binding_sites": [], "products": [], "num_products": 0})
    result = cloning.pcr_complex_multi_primers(
        {"sequence": "ACGTACGT", "primers": ["ACGT", "CGTA"]}, driver
    )
    assert result == {"binding_sites": [], "products": [], "num_products": 0}
    assert driver.last_args() == {
        "sequence": "ACGTACGT",
        "primers": ["ACGT", "CGTA"],
        "circular": True,
    }


def test_pcr_complex_multi_primers_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.pcr_complex_multi_primers({"sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# digest_sequence
# --------------------------------------------------------------------------


def test_digest_sequence_round_trip_and_result():
    driver = _driver({"fragments": [], "num_fragments": 0, "cut_sites": {}})
    result = cloning.digest_sequence(
        {"dna_sequence": "GAATTC", "enzyme_names": ["EcoRI"]}, driver
    )
    assert result == {"fragments": [], "num_fragments": 0, "cut_sites": {}}
    assert driver.last_args() == {
        "dna_sequence": "GAATTC",
        "enzyme_names": ["EcoRI"],
        "is_circular": True,
    }


def test_digest_sequence_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.digest_sequence({"dna_sequence": "GAATTC"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# golden_gate
# --------------------------------------------------------------------------


def test_golden_gate_round_trip_and_result():
    driver = _driver({"assembled_sequence": "ACGT", "length": 4, "is_circular": True})
    result = cloning.golden_gate(
        {
            "fragments": [{"sequence": "AAAA"}, {"sequence": "TTTT", "name": "insert"}],
            "circular": [True, False],
            "enzyme_name": "BsaI",
        },
        driver,
    )
    assert result["is_circular"] is True
    assert driver.last_args() == {
        "fragments": [{"sequence": "AAAA", "name": None}, {"sequence": "TTTT", "name": "insert"}],
        "circular": [True, False],
        "enzyme_name": "BsaI",
    }


def test_golden_gate_malformed_fragment_missing_sequence():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.golden_gate(
            {"fragments": [{"name": "no_sequence_here"}], "circular": [True], "enzyme_name": "BsaI"},
            driver,
        )
    assert driver.calls == []


# --------------------------------------------------------------------------
# oligo_assembly
# --------------------------------------------------------------------------


def test_oligo_assembly_round_trip_and_result():
    driver = _driver({"overhang_type": "blunt", "duplex_length": 4})
    result = cloning.oligo_assembly({"seq1": "ACGT", "seq2": "ACGT"}, driver)
    assert result == {"overhang_type": "blunt", "duplex_length": 4}
    assert driver.last_args() == {"seq1": "ACGT", "seq2": "ACGT"}


def test_oligo_assembly_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.oligo_assembly({"seq1": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# gibson_assembly
# --------------------------------------------------------------------------


def test_gibson_assembly_round_trip_and_result():
    driver = _driver({"assembled_sequence": "ACGTACGT", "length": 8, "is_circular": False})
    result = cloning.gibson_assembly({"fragments": ["ACGTACGT", "ACGTGGGG"]}, driver)
    assert result["length"] == 8
    assert driver.last_args() == {"fragments": ["ACGTACGT", "ACGTGGGG"], "min_overlap": 15}


def test_gibson_assembly_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.gibson_assembly({}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# find_restriction_sites
# --------------------------------------------------------------------------


def test_find_restriction_sites_round_trip_and_result():
    driver = _driver({"sites": {}})
    result = cloning.find_restriction_sites(
        {"dna_sequence": "GAATTC", "enzymes": ["EcoRI"]}, driver
    )
    assert result == {"sites": {}}
    assert driver.last_args() == {
        "dna_sequence": "GAATTC",
        "enzymes": ["EcoRI"],
        "is_circular": True,
    }


def test_find_restriction_sites_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.find_restriction_sites({"dna_sequence": "GAATTC"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# find_restriction_enzymes
# --------------------------------------------------------------------------


def test_find_restriction_enzymes_round_trip_and_result():
    driver = _driver({"enzymes_found": {}, "num_enzymes_with_sites": 0})
    result = cloning.find_restriction_enzymes({"sequence": "GAATTC"}, driver)
    assert result == {"enzymes_found": {}, "num_enzymes_with_sites": 0}
    assert driver.last_args() == {"sequence": "GAATTC", "is_circular": False}


def test_find_restriction_enzymes_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.find_restriction_enzymes({}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# design_primers_with_overhangs
# --------------------------------------------------------------------------


def test_design_primers_with_overhangs_round_trip_and_result():
    driver = _driver({"forward_primer": "AATTACGTACGTACGTACGT", "forward_tm": 60.0})
    result = cloning.design_primers_with_overhangs(
        {
            "sequence": "ACGTACGTACGTACGTACGTACGT",
            "forward_overhang": "AATT",
            "reverse_overhang": "GGCC",
            "target_tm": 60.0,
        },
        driver,
    )
    assert result["forward_tm"] == 60.0
    assert driver.last_args() == {
        "sequence": "ACGTACGTACGTACGTACGTACGT",
        "forward_overhang": "AATT",
        "reverse_overhang": "GGCC",
        "target_tm": 60.0,
        "min_primer_length": 15,
    }


def test_design_primers_with_overhangs_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.design_primers_with_overhangs({"sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# find_sequence_mutations
# --------------------------------------------------------------------------


def test_find_sequence_mutations_round_trip_and_result():
    driver = _driver({"mutations": [], "num_mutations": 0})
    result = cloning.find_sequence_mutations(
        {"query_sequence": "ACGT", "reference_sequence": "ACGA"}, driver
    )
    assert result == {"mutations": [], "num_mutations": 0}
    assert driver.last_args() == {
        "query_sequence": "ACGT",
        "reference_sequence": "ACGA",
        "query_start": 1,
    }


def test_find_sequence_mutations_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.find_sequence_mutations({"query_sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# get_molecular_cloning_instructions (no args)
# --------------------------------------------------------------------------


def test_get_molecular_cloning_instructions_result_and_no_args():
    driver = _driver({"plasmid_numbering": "..."})
    result = cloning.get_molecular_cloning_instructions({}, driver)
    assert result == {"plasmid_numbering": "..."}
    assert driver.last_args() == {}


# --------------------------------------------------------------------------
# calculate_element_distances
# --------------------------------------------------------------------------


def test_calculate_element_distances_round_trip_and_result():
    driver = _driver({"distances": [], "num_pairs": 0})
    result = cloning.calculate_element_distances(
        {
            "sequence_length": 5000,
            "element_positions": [
                {"start": 0, "end": 100, "name": "promoter"},
                {"start": 200, "end": 300},
            ],
        },
        driver,
    )
    assert result == {"distances": [], "num_pairs": 0}
    assert driver.last_args() == {
        "sequence_length": 5000,
        "element_positions": [
            {"start": 0, "end": 100, "name": "promoter"},
            {"start": 200, "end": 300, "name": None},
        ],
        "is_circular": True,
    }


def test_calculate_element_distances_malformed_element_missing_end():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.calculate_element_distances(
            {"sequence_length": 5000, "element_positions": [{"start": 0}]}, driver
        )
    assert driver.calls == []


# --------------------------------------------------------------------------
# design_knockout_sgrna
# --------------------------------------------------------------------------


def test_design_knockout_sgrna_round_trip_and_result():
    driver = _driver({"gene_name": "TP53", "guides": [], "num_guides": 0})
    result = cloning.design_knockout_sgrna({"gene_name": "TP53"}, driver)
    assert result == {"gene_name": "TP53", "guides": [], "num_guides": 0}
    assert driver.last_args() == {
        "gene_name": "TP53",
        "species": "human",
        "num_guides": 1,
        "species_token": "human",
    }


def test_design_knockout_sgrna_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.design_knockout_sgrna({}, driver)
    assert driver.calls == []


def test_design_knockout_sgrna_rejects_path_traversal_species():
    driver = _driver()
    with pytest.raises(PathTraversalError):
        cloning.design_knockout_sgrna(
            {"gene_name": "TP53", "species": "../../etc/passwd"}, driver
        )
    assert driver.calls == []


# --------------------------------------------------------------------------
# design_golden_gate_oligos
# --------------------------------------------------------------------------


def test_design_golden_gate_oligos_round_trip_and_result():
    driver = _driver({"enzyme": "BsmBI", "forward_oligo": "...", "reverse_oligo": "..."})
    result = cloning.design_golden_gate_oligos(
        {"insert_sequence": "ACGTACGTAC", "backbone_sequence": "TTTTGGGGCC"}, driver
    )
    assert result["enzyme"] == "BsmBI"
    assert driver.last_args() == {
        "insert_sequence": "ACGTACGTAC",
        "backbone_sequence": "TTTTGGGGCC",
        "enzyme_name": "BsmBI",
        "is_circular": True,
    }


def test_design_golden_gate_oligos_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.design_golden_gate_oligos({"insert_sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# get_oligo_annealing_protocol (no args)
# --------------------------------------------------------------------------


def test_get_oligo_annealing_protocol_result_and_no_args():
    driver = _driver({"name": "Standard oligo annealing (no phosphorylation)"})
    result = cloning.get_oligo_annealing_protocol({}, driver)
    assert result == {"name": "Standard oligo annealing (no phosphorylation)"}
    assert driver.last_args() == {}


# --------------------------------------------------------------------------
# get_golden_gate_assembly_protocol
# --------------------------------------------------------------------------


def test_get_golden_gate_assembly_protocol_round_trip_and_result():
    driver = _driver({"enzyme": "BsmBI", "insert_amounts": []})
    result = cloning.get_golden_gate_assembly_protocol(
        {"enzyme_name": "BsmBI", "vector_length": 3000}, driver
    )
    assert result["enzyme"] == "BsmBI"
    assert driver.last_args() == {
        "enzyme_name": "BsmBI",
        "vector_length": 3000,
        "num_inserts": 1,
        "vector_amount_ng": 75.0,
        "insert_lengths": None,
        "is_library_prep": False,
    }


def test_get_golden_gate_assembly_protocol_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.get_golden_gate_assembly_protocol({"enzyme_name": "BsmBI"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# get_bacterial_transformation_protocol
# --------------------------------------------------------------------------


def test_get_bacterial_transformation_protocol_round_trip_and_result():
    driver = _driver({"antibiotic": "ampicillin", "selection_concentration_ug_ml": 100})
    result = cloning.get_bacterial_transformation_protocol({}, driver)
    assert result["antibiotic"] == "ampicillin"
    assert driver.last_args() == {"antibiotic": "ampicillin", "is_repetitive": False}


def test_get_bacterial_transformation_protocol_malformed_arg_type():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.get_bacterial_transformation_protocol({"is_repetitive": "not-a-bool"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# design_primer
# --------------------------------------------------------------------------


def test_design_primer_round_trip_and_result():
    driver = _driver({"primer": {"sequence": "ACGT" * 5}, "num_candidates": 1})
    result = cloning.design_primer({"sequence": "ACGT" * 20, "start_pos": 5}, driver)
    assert result["num_candidates"] == 1
    assert driver.last_args() == {
        "sequence": "ACGT" * 20,
        "start_pos": 5,
        "primer_length": 20,
        "min_gc": 0.4,
        "max_gc": 0.6,
        "min_tm": 55.0,
        "max_tm": 65.0,
        "search_window": 100,
    }


def test_design_primer_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.design_primer({"sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# design_verification_primers
# --------------------------------------------------------------------------


def test_design_verification_primers_round_trip_and_result():
    driver = _driver({"reused_primers": []})
    result = cloning.design_verification_primers(
        {"plasmid_sequence": "ACGT" * 50, "target_region": (100, 200)}, driver
    )
    assert result == {"reused_primers": []}
    # `target_region` round-trips through the JSON args file as a list (a
    # Python tuple serializes to a JSON array, and `last_args()` reads it
    # back with `json.load`, which never reconstructs tuples).
    assert driver.last_args() == {
        "plasmid_sequence": "ACGT" * 50,
        "target_region": [100, 200],
        "existing_primers": None,
        "is_circular": True,
        "coverage_length": 800,
        "primer_length": 20,
        "min_gc": 0.4,
        "max_gc": 0.6,
        "min_tm": 55.0,
        "max_tm": 65.0,
    }


def test_design_verification_primers_missing_required_arg():
    driver = _driver()
    with pytest.raises(ValidationError):
        cloning.design_verification_primers({"plasmid_sequence": "ACGT"}, driver)
    assert driver.calls == []


# --------------------------------------------------------------------------
# register_cloning_tools
# --------------------------------------------------------------------------


def test_register_cloning_tools_registers_every_tool_name():
    class _FakeRegistry:
        def __init__(self):
            self.registered = {}

        def register_server(self, name, handler):
            self.registered[name] = handler

    registry = _FakeRegistry()
    driver = FakeSandboxDriver()
    names = cloning.register_cloning_tools(registry, driver)

    expected_names = {
        "annotate_open_reading_frames",
        "annotate_plasmid",
        "get_gene_coding_sequence",
        "get_plasmid_sequence",
        "align_sequences",
        "pcr_simple",
        "pcr_complex_multi_primers",
        "digest_sequence",
        "golden_gate",
        "oligo_assembly",
        "gibson_assembly",
        "find_restriction_sites",
        "find_restriction_enzymes",
        "design_primers_with_overhangs",
        "find_sequence_mutations",
        "get_molecular_cloning_instructions",
        "calculate_element_distances",
        "design_knockout_sgrna",
        "design_golden_gate_oligos",
        "get_oligo_annealing_protocol",
        "get_golden_gate_assembly_protocol",
        "get_bacterial_transformation_protocol",
        "design_primer",
        "design_verification_primers",
    }
    assert set(names) == expected_names
    assert set(registry.registered.keys()) == expected_names
    assert all(callable(h) for h in registry.registered.values())


def test_register_cloning_tools_binds_driver_so_registered_handler_is_single_arg_callable():
    class _FakeRegistry:
        def __init__(self):
            self.registered = {}

        def register_server(self, name, handler):
            self.registered[name] = handler

    registry = _FakeRegistry()
    driver = _driver({"ok": True})
    cloning.register_cloning_tools(registry, driver)

    # Mirrors how `MCPServerRegistry.route()` actually invokes a registered
    # handler -- a single positional `arguments` dict, `driver` already
    # bound via `functools.partial` at registration time.
    result = registry.registered["pcr_simple"](
        {"sequence": "ACGT", "forward_primer": "AC", "reverse_primer": "GT"}
    )
    assert result == {"ok": True}
