# Action tool catalog (Fase 5 source-of-truth)

Transcrito verbatim (nome + params exatos, required/optional/default) do catálogo Biomni colado
pelo usuário. Cada entrada abaixo é candidata a virar um MCP tool em
`backend/src/infrastructure/tools/<categoria>.py`, executado dentro do sandbox bwrap
(`BubblewrapSandboxDriver`), tier A/B/C/D conforme a seção "Decisões de arquitetura" do plano.

**Tiering obrigatório antes de implementar cada tool** (não pular esta etapa):
- **A** = lib determinística real sem modelo estatístico (biopython/RDKit/libsbml/cobra/etc).
- **B** = método numérico real (scipy curve_fit / scipy.integrate ODE / sklearn NMF / fórmula fechada tipo MIRD).
- **C** = image processing real mas genérico (scikit-image/opencv/trackpy/cellpose) — documentar "método geral, não validado clinicamente".
- **D** = exige checkpoint pré-treinado proprietário/GPU cluster não disponível localmente (TxGNN, UCE, DiffDock, cryoSPARC) — registrar tool com schema correto, handler levanta `NotImplementedError` citando o que falta, documentado em `backend/docs/tools/UNSUPPORTED.md`.

Todo handler: valida args via Pydantic, serializa pra JSON, roda um script-template dentro do
workspace via `driver.execute_python_script`, parseia stdout JSON. Qualquer arg que seja caminho de
arquivo DEVE passar por `ensure_safe_relative_path` (`domain/services/path_guard.py`).

---

## Categoria: Literature & search support

- **fetch_supplementary_info_from_doi**(doi: str, output_dir: str = "supplementary_info") — fetch supplementary info for a paper by DOI, save to dir. Tier A (real HTTP + parsing, not sandboxed — network I/O, treat like a DB adapter).
- **query_arxiv**(query: str, max_papers: int = 10) — query arXiv, return papers. Tier A (network).
- **query_scholar**(query: str) — query Google Scholar, return first result. Tier A (network, fragile — Scholar has no official API, expect scraping; document rate-limit/ToS risk).
- **query_pubmed**(query: str, max_papers: int = 10, max_retries: int = 3) — query PubMed (NCBI Entrez), return papers. Tier A (network, real Entrez API).
- **search_google**(query: str, num_results: int = 3, language: str = "en") — Google search, formatted results. Tier A (network — needs a real search API/key, e.g. Google Custom Search; document `GOOGLE_SEARCH_API_KEY` setting needed).
- **extract_url_content**(url: str) — extract text content of a webpage (requests + BeautifulSoup). Tier A (network + parsing).
- **extract_pdf_content**(url: str) — extract text content from a PDF at a URL. Tier A (network + pypdf, already a default dependency for RAG ingestion — reuse `PypdfDocumentParser` pattern).

These 7 are network/IO tools like the DB adapters (not compute-heavy) — implement in-process
(no sandbox needed), same trust tier as `bio_direct_adapters.py`, OR route through sandbox if
`extract_url_content`/`extract_pdf_content` need to fetch untrusted third-party content (safer:
sandbox them, since they fetch arbitrary attacker-influenceable URLs).

## Categoria: Molecular cloning & DNA engineering (Tier A — biopython/Bio.Restriction real logic)

- **annotate_open_reading_frames**(sequence: str, min_length: int, search_reverse: bool = False, filter_subsets: bool = False) — find all ORFs (Biopython), forward + optional reverse complement.
- **annotate_plasmid**(sequence: str, is_circular: bool = True, return_plot: bool = False) — annotate DNA sequence via pLannotate CLI (needs `plannotate` conda package, Fase 1).
- **get_gene_coding_sequence**(gene_name: str, organism: str, email: Optional[str] = None) — retrieve CDS from NCBI Entrez.
- **get_plasmid_sequence**(identifier: str, is_addgene: Optional[bool] = None) — unified Addgene/NCBI plasmid sequence lookup.
- **align_sequences**(long_seq: str, short_seqs: Union[str, List[str]]) — align short primers to a longer sequence, allow 1 mismatch, both strands.
- **pcr_simple**(sequence: str, forward_primer: str, reverse_primer: str, circular: bool = False) — simulate PCR amplification.
- **pcr_complex_multi_primers**(sequence: str, primers: List[str], circular: bool = True) — simulate PCR with multiple primers, all combinations.
- **digest_sequence**(dna_sequence: str, enzyme_names: List[str], is_circular: bool = True) — simulate restriction digest, return fragments+properties (Bio.Restriction).
- **golden_gate**(fragments: List[Dict], circular: List[bool], enzyme_name: str) — simulate Golden Gate assembly (Type IIS enzymes: BsaI/BbsI/BtgZI/BsmBI/etc).
- **oligo_assembly**(seq1: str, seq2: str) — assemble two sequences into an oligo with overhangs, auto-detect overhang type/length.
- **gibson_assembly**(fragments: List[str], min_overlap: int = 15) — simulate Gibson Assembly.
- **find_restriction_sites**(dna_sequence: str, enzymes: List[str], is_circular: bool = True) — identify restriction sites for specified enzymes.
- **find_restriction_enzymes**(sequence: str, is_circular: bool = False) — find common restriction sites, return cut positions.
- **design_primers_with_overhangs**(sequence: str, forward_overhang: str, reverse_overhang: str, target_tm: float, min_primer_length: int = 15) — design primer pair with overhangs.
- **find_sequence_mutations**(query_sequence: str, reference_sequence: str, query_start: int = 1) — compare query vs reference, identify mutations.
- **get_molecular_cloning_instructions**() — returns static dict of cloning/plasmid-circularity guidance (no args).
- **calculate_element_distances**(sequence_length: int, element_positions: List[Dict], is_circular: bool = True) — pairwise distances between elements on a plasmid.
- **design_knockout_sgrna**(gene_name: str, species: str = "human", num_guides: int = 1) — sgRNA design by searching pre-computed libraries (needs a bundled/data-lake sgRNA library — if absent, fail loud pointing at `fetch_data_lake.py`, don't fabricate guides).
- **design_golden_gate_oligos**(insert_sequence: str, backbone_sequence: str, enzyme_name: str = "BsmBI", is_circular: bool = True) — design oligos w/ Type IIS overhangs from backbone restriction analysis.
- **get_oligo_annealing_protocol**() — static standard annealing protocol (no phosphorylation), no args.
- **get_golden_gate_assembly_protocol**(enzyme_name: str, vector_length: int, num_inserts: int = 1, vector_amount_ng: float = 75.0, insert_lengths: Optional[List[int]] = None, is_library_prep: bool = False) — customized Golden Gate protocol.
- **get_bacterial_transformation_protocol**(antibiotic: str = "ampicillin", is_repetitive: bool = False) — standard transformation protocol.
- **design_primer**(sequence: str, start_pos: int, primer_length: int = 20, min_gc: float = 0.4, max_gc: float = 0.6, min_tm: float = 55.0, max_tm: float = 65.0, search_window: int = 100) — design single primer in window.
- **design_verification_primers**(plasmid_sequence: str, target_region: Tuple[int,int], existing_primers: Optional[List[Dict]] = None, is_circular: bool = True, coverage_length: int = 800, primer_length: int = 20, min_gc: float = 0.4, max_gc: float = 0.6, min_tm: float = 55.0, max_tm: float = 65.0) — Sanger verification primer design, reuse existing primer pool first.

## Categoria: Genomics & population genetics

- **liftover_coordinates**(chromosome: str, position: int, input_format: str, output_format: str, data_path: str) — hg19<->hg38 liftover (pyliftover; `data_path` = chain files, part of data lake). Tier A.
- **bayesian_finemapping_with_deep_vi**(gwas_summary_path: str, ld_matrix: ndarray, n_iterations: int = 5000, learning_rate: float = 0.01, hidden_dim: int = 64, credible_threshold: float = 0.95) — Bayesian fine-mapping via deep variational inference, posterior inclusion probabilities + credible sets. Tier B (real VI implementable with torch/numpyro, simplified but genuine — not a pretrained checkpoint dependency).
- **analyze_cas9_mutation_outcomes**(reference_sequences: dict, edited_sequences: dict, cell_line_info: Optional[dict] = None, output_prefix: str = "cas9_mutation_analysis") — categorize Cas9-induced mutations. Tier A (sequence diff/alignment logic).
- **analyze_crispr_genome_editing**(original_sequence: str, edited_sequence: str, guide_rna: str, repair_template: Optional[str] = None) — compare pre/post CRISPR sequences. Tier A.
- **perform_crispr_cas9_genome_editing**(guide_rna_sequences: List[str], target_genomic_loci: str, cell_tissue_type: str) — simulate CRISPR-Cas9 editing process (guide design/delivery/analysis). Tier A (simulation, not wet-lab; documented as such).
- **simulate_demographic_history**(num_samples: int = 10, sequence_length: int = 100000, recombination_rate: float = 1e-8, mutation_rate: float = 1e-8, demographic_model: str = "constant", demographic_params: Optional[dict] = None, coalescent_model: str = "kingman", beta_coalescent_param: Optional[float] = None, random_seed: Optional[int] = None, output_file: str = "simulated_sequences.vcf") — msprime coalescent simulation. Tier A (real msprime call).
- **identify_transcription_factor_binding_sites**(sequence: str, tf_name: str, threshold: float = 0.8, output_file: Optional[str] = None) — TF binding site search (JASPAR motif scan via Biopython/MOODS). Tier A.
- **fit_genomic_prediction_model**(genotypes: ndarray, phenotypes: ndarray, fixed_effects: Optional[ndarray] = None, model_type: str = "additive", output_file: str = "genomic_prediction_results.csv") — linear mixed model genomic prediction. Tier B (statsmodels/real LMM).
- **perform_pcr_and_gel_electrophoresis**(genomic_dna: str, forward_primer: Optional[str] = None, reverse_primer: Optional[str] = None, target_region: Optional[tuple] = None, annealing_temp: float = 58, extension_time: int = 30, cycles: int = 35, gel_percentage: float = 2.0, output_prefix: str = "pcr_result") — PCR + simulated gel image. Tier A/C (simulation + a rendered gel image, not a real wet-lab gel).
- **analyze_protein_phylogeny**(fasta_sequences: str, output_dir: str = "./", alignment_method: str = "clustalw", tree_method: str = "fasttree") — MSA + phylogenetic tree (mafft/muscle/fasttree CLI from sandbox toolkit). Tier A.

## Categoria: Single-cell / omics / regulatory genomics

- **annotate_celltype_scRNA**(adata_filename: str, data_dir: str, data_info: str, cluster: str = "leiden", llm: str = "claude-3-5-sonnet-20241022", composition: Optional[DataFrame] = None, DATA_LAKE: str = "/dfs/project/bioagentos/data_lake") — annotate cell types via LLM + marker genes after leiden clustering (scanpy). Tier A/B hybrid: real scanpy clustering + real LLM call (reuse OSW's existing `ModelProviderPort`, NOT a hardcoded model string — adapt default to whatever OSW's configured provider is).
- **create_scvi_embeddings_scRNA**(adata_filename: str, batch_key: str, label_key: str, data_dir: str) — scVI/scANVI embeddings (needs `scvi-tools` + torch, heavy — confirm in Fase 1 environment.yml). Tier A.
- **create_harmony_embeddings_scRNA**(adata_filename: str, batch_key: str, data_dir: str) — Harmony batch integration (harmonypy). Tier A.
- **get_uce_embeddings_scRNA**(adata_filename: str, data_dir: str, DATA_ROOT: str = "/dfs/project/bioagentos/data/singlecell/", custom_args: Optional[List[str]] = None) — **Tier D**, GPU required per Biomni's own docs ("not currently supported in the web UI").
- **map_to_ima_interpret_scRNA**(adata_filename: str, data_dir: str, custom_args: Optional[dict] = None) — **Tier D**, same UCE/GPU dependency as above.
- **get_rna_seq_archs4**(gene_name: str, K: int = 10) — top-K tissue TPM for a gene from ARCHS4. Tier A (real HTTP call to ARCHS4 API — consider placing as a DB adapter instead of an action tool).
- **get_gene_set_enrichment_analysis_supported_database_list**() — list supported enrichment DBs (gseapy `gseapy.get_library_name()` — real, or data-lake MSigDB manifest).
- **gene_set_enrichment_analysis**(genes: list, top_k: int = 10, database: str = "ontology", background_list: Optional[list] = None, plot: bool = False) — gseapy enrichment. Tier A.
- **analyze_chromatin_interactions**(hic_file_path: str, regulatory_elements_bed: str, output_dir: str = "./output") — Hi-C enhancer-promoter/TAD analysis (`cooler`). Tier A.
- **analyze_comparative_genomics_and_haplotypes**(sample_fasta_files: List[str], reference_genome_path: str, output_dir: str = "./output") — align samples to reference, variant/haplotype analysis (bwa/samtools/bcftools). Tier A.
- **perform_chipseq_peak_calling_with_macs2**(chip_seq_file: str, control_file: str, output_name: str = "macs2_output", genome_size: str = "hs", q_value: float = 0.05) — MACS2 peak calling. Tier A.
- **find_enriched_motifs_with_homer**(peak_file: str, genome: str = "hg38", background_file: Optional[str] = None, motif_length: str = "8,10,12", output_dir: str = "./homer_motifs", num_motifs: int = 10, threads: int = 4) — HOMER motif discovery. Tier A.
- **analyze_genomic_region_overlap**(region_sets: list, output_prefix: str = "overlap_analysis") — bedtools-style overlap analysis across N region sets. Tier A.
- **analyze_atac_seq_differential_accessibility**(treatment_bam: str, control_bam: str, output_dir: str = "./atac_results", genome_size: str = "hs", q_value: float = 0.05, name_prefix: str = "atac") — MACS2-based ATAC-seq peak calling + differential accessibility. Tier A.
- **analyze_ddr_network_in_cancer**(expression_data_path: str, mutation_data_path: str, output_dir: str = "./results") — DNA Damage Response network alteration analysis. Tier B (stats on expression/mutation tables).
- **detect_and_annotate_somatic_mutations**(tumor_bam: str, normal_bam: str, reference_genome: str, output_prefix: str, snpeff_database: str = "GRCh38.105") — GATK Mutect2 + FilterMutectCalls + SnpEff (all need adding to `environment.yml`, Fase 1). Tier A.
- **detect_and_characterize_structural_variations**(bam_file_path: str, reference_genome_path: str, output_dir: str, cosmic_db_path: Optional[str] = None, clinvar_db_path: Optional[str] = None) — LUMPY SV detection + COSMIC/ClinVar annotation (LUMPY needs adding to `environment.yml`). Tier A.
- **perform_gene_expression_nmf_analysis**(expression_data_path: str, n_components: int = 10, normalize: bool = True, output_dir: str = "nmf_results", random_state: int = 42) — sklearn NMF for metagene/subtype extraction. Tier B.

## Categoria: Cell biology & imaging (Tier C — real scikit-image/opencv/trackpy pipelines, general-purpose, not clinically validated)

- **analyze_cell_migration_metrics**(image_sequence_path: str, pixel_size_um: float = 1.0, time_interval_min: float = 1.0, min_track_length: int = 10, output_dir: str = "./output") — cell tracking + migration metrics from time-lapse (trackpy/cellpose).
- **analyze_calcium_imaging_data**(image_stack_path: str, output_dir: str = "./output") — neuronal activity from calcium imaging TIFF stack (cell counts, event rates, decay times, SNR).
- **analyze_myofiber_morphology**(image_path: str, nuclei_channel: int = 2, myofiber_channel: int = 1, threshold_method: str = "otsu", output_dir: str = "./output") — myofiber morphology quantification.
- **quantify_cell_cycle_phases_from_microscopy**(image_paths: List[str], output_dir: str = "./results") — % cells per cell-cycle phase (Calcofluor white staining).
- **quantify_and_cluster_cell_motility**(image_sequence_path: str, output_dir: str = "./results", num_clusters: int = 3) — motility feature extraction + clustering (trackpy + sklearn KMeans).
- **analyze_mitochondrial_morphology_and_potential**(morphology_image_path: str, potential_image_path: str, output_dir: str = "./output") — mitochondrial morphology + membrane potential (MTS-GFP/TMRE).
- **analyze_cell_morphology_and_cytoskeleton**(image_path: str, output_dir: str = "./results", threshold_method: str = "otsu") — cell morphology + cytoskeletal organization.
- **analyze_tissue_deformation_flow**(image_sequence: Union[list, ndarray], output_dir: str = "results", pixel_scale: float = 1.0) — tissue deformation/flow dynamics (optical flow).
- **analyze_cell_senescence_and_apoptosis**(fcs_file_path: str) — flow cytometry SA-β-Gal/Annexin-V/7-AAD quantification (`flowkit`/`FlowIO`).
- **perform_facs_cell_sorting**(cell_suspension_data: str, fluorescence_parameter: str, threshold_min: Optional[float] = None, threshold_max: Optional[float] = None, output_file: str = "sorted_cells.csv") — simulated FACS gating.
- **analyze_flow_cytometry_immunophenotyping**(fcs_file_path: str, gating_strategy: dict, compensation_matrix: Optional[ndarray] = None, output_dir: str = "./results") — flow cytometry population gating.
- **analyze_cfse_cell_proliferation**(fcs_file_path: str, cfse_channel: str = "FL1-A", lymphocyte_gate: Optional[tuple] = None) — CFSE dilution proliferation analysis.
- **estimate_cell_cycle_phase_durations**(flow_cytometry_data: dict, initial_estimates: dict) — dual-nucleoside pulse-labeling model fit. Tier B (scipy optimize).
- **predict_protein_disorder_regions**(protein_sequence: str, threshold: float = 0.5, output_file: str = "disorder_prediction_results.csv") — IUPred2A-style disorder prediction. Tier A (real, documented algorithm — implement the published IUPred method, not a black box).

## Categoria: Biophysics & biochemical assays (Tier A/B — real scipy curve-fitting / documented algorithms)

- **analyze_circular_dichroism_spectra**(sample_name: str, sample_type: str, wavelength_data, cd_signal_data, temperature_data=None, thermal_cd_data=None, output_dir: str = "./") — CD secondary-structure + thermal stability.
- **analyze_rna_secondary_structure_features**(dot_bracket_structure: str, sequence: Optional[str] = None) — dot-bracket structural feature calc + optional ViennaRNA energy calc.
- **analyze_protease_kinetics**(time_points: ndarray, fluorescence_data: ndarray, substrate_concentrations: ndarray, enzyme_concentration: float, output_prefix: str = "protease_kinetics", output_dir: str = "./") — Michaelis-Menten fit from fluorogenic assay.
- **analyze_enzyme_kinetics_assay**(enzyme_name: str, substrate_concentrations, enzyme_concentration: float, modulators: Optional[dict] = None, time_points: Optional[list] = None, output_dir: str = "./") — dose-dependent modulator kinetics.
- **analyze_itc_binding_thermodynamics**(itc_data_path: Optional[str] = None, itc_data: Optional[ndarray] = None, temperature: float = 298.15, protein_concentration: Optional[float] = None, ligand_concentration: Optional[float] = None) — ITC binding affinity/thermodynamics fit.
- **analyze_protein_conservation**(protein_sequences: List[str], output_dir: str = "./") — MSA + phylogenetics for conserved-region ID (reuse cloning-category MSA logic).
- **analyze_atp_luminescence_assay**(data_file: str, standard_curve_file: str, normalization_method: str = "cell_count", normalization_data: Optional[Union[str,dict]] = None) — luminescence ATP standard-curve fit.
- **analyze_bacterial_growth_curve**(time_points, od_values, strain_name: str, output_dir: str = ".") — growth rate/doubling time/lag phase fit.
- **analyze_bacterial_growth_rate**(time_points, od_measurements, strain_name: str = "Unknown strain", output_dir: str = "./") — same family, OD600-based.

## Categoria: Imunologia

- **isolate_purify_immune_cells**(tissue_type: str, target_cell_type: str, enzyme_type: str = "collagenase", macs_antibody: Optional[str] = None, digestion_time_min: int = 45) — protocol generator (Tier A, text output, no compute).
- **track_immune_cells_under_flow**(image_sequence_path: str, output_dir: str = "./output", pixel_size_um: float = 1.0, time_interval_sec: float = 1.0, flow_direction: str = "right") — immune cell tracking under flow.
- **analyze_cytokine_production_in_cd4_tcells**(fcs_files_dict: dict, output_dir: str = "./results") — IFN-γ/IL-17 flow cytometry across stim conditions.
- **analyze_ebv_antibody_titers**(raw_od_data: dict, standard_curve_data: dict, sample_metadata: dict, output_dir: str = "./") — ELISA standard-curve titer fit.
- **analyze_cns_lesion_histology**(image_path: str, output_dir: str = "./output", stain_type: str = "H&E") — immune infiltration/demyelination/tissue damage quantification.
- **analyze_immunohistochemistry_image**(image_path: str, protein_name: str = "Unknown", output_dir: str = "./ihc_results/") — IHC protein expression quantification.

## Categoria: Fisiologia / cardio / neuro / imaging

- **analyze_aortic_diameter_and_geometry**(image_path: str, output_dir: str = "./output") — aortic geometry from cardiovascular imaging (DICOM/JPG/PNG).
- **analyze_thrombus_histology**(image_path: str, output_dir: str = "./output") — H&E thrombus component classification.
- **analyze_intracellular_calcium_with_rhod2**(background_image_path: str, control_image_path: str, sample_image_path: str, output_dir: str = "./output") — Rhod-2 calcium quantification.
- **quantify_corneal_nerve_fibers**(image_path: str, marker_type: str, output_dir: str = "./output", threshold_method: str = "otsu") — IF corneal nerve fiber density.
- **segment_and_quantify_cells_in_multiplexed_images**(image_path: str, markers_list: List[str], nuclear_channel_index: int = 0, output_dir: str = "./output") — multichannel tissue image cell segmentation.
- **analyze_bone_microct_morphometry**(input_file_path: str, output_dir: str = "./results", threshold_value: Optional[float] = None) — bone microarchitecture from micro-CT (BMD/BV/Tb.N/Tb.Th/Tb.Sp).
- **reconstruct_3d_face_from_mri**(mri_file_path: str, output_dir: str = "./output", subject_id: str = "subject", threshold_value: int = 300) — 3D facial model from MRI (NIfTI, needs `nibabel`).
- **analyze_abr_waveform_p1_metrics**(time_ms, amplitude_uv) — P1 amplitude/latency from ABR waveform.
- **analyze_ciliary_beat_frequency**(video_path: str, roi_count: int = 5, min_freq: float = 0, max_freq: float = 30, output_dir: str = "./") — FFT analysis of ciliary beat video.
- **analyze_protein_colocalization**(channel1_path: str, channel2_path: str, output_dir: str = "./output", threshold_method: str = "otsu") — colocalization (Pearson/Manders coefficients).
- **perform_cosinor_analysis**(time_data, physiological_data, period: float = 24.0) — circadian rhythm cosinor fit.
- **calculate_brain_adc_map**(dwi_file_path: str, b_values: List[float], output_path: str = "adc_map.nii.gz", mask_file_path: Optional[str] = None) — ADC map from diffusion MRI (monoexponential fit).
- **analyze_endolysosomal_calcium_dynamics**(time_points, luminescence_values, treatment_time: Optional[float] = None, cell_type: Optional[str] = None, treatment_name: Optional[str] = None, output_file: str = "calcium_analysis_results.txt") — ELGA/ELGA1 probe dynamics.
- **analyze_fatty_acid_composition_by_gc**(gc_data_file: str, tissue_type: str, sample_id: str, output_directory: str = "./results") — GC fatty acid composition.
- **analyze_hemodynamic_data**(pressure_data: ndarray, sampling_rate: float, output_file: str = "hemodynamic_results.csv") — blood pressure -> hemodynamic parameters.
- **simulate_thyroid_hormone_pharmacokinetics**(parameters: dict, initial_conditions: dict, time_span: tuple = (0,24), time_points: int = 100) — ODE-based thyroid hormone PK across compartments.
- **quantify_amyloid_beta_plaques**(image_path: str, output_dir: str = "./results", threshold_method: str = "otsu", min_plaque_size: int = 50, manual_threshold: int = 127) — amyloid-beta plaque detection/quantification.
- **decode_behavior_from_neural_trajectories**(neural_data: ndarray, behavioral_data: ndarray, n_components: int = 10, output_dir: str = "./results") — neural trajectory -> behavior decoding (PCA + regression).

## Categoria: Drug discovery & pharmacology

- **run_diffdock_with_smiles**(pdb_path: str, smiles_string: str, local_output_dir: str, gpu_device: int = 0, use_gpu: bool = True) — **Tier D**, GPU + Docker container required per Biomni's own docs ("not currently supported in the web UI").
- **docking_autodock_vina**(smiles_list: List[str], receptor_pdb_file: str, box_center: List[float], box_size: List[float], ncpu: int = 1) — real AutoDock Vina docking (CLI in `environment.yml`). Tier A.
- **run_autosite**(pdb_file: str, output_dir: str, spacing: float = 1.0) — AutoSite binding-site detection (ADFRsuite CLI). Tier A.
- **retrieve_topk_repurposing_drugs_from_disease_txgnn**(disease_name: str, k: int = 5) — **Tier D**, requires a trained TxGNN checkpoint not bundled/obtainable locally.
- **predict_admet_properties**(smiles_list: List[str], ADMET_model_type: str = "MPNN") — DeepPurpose ADMET prediction, pretrained weights downloaded on first call by the lib itself — document as such, not silently bundled.
- **predict_binding_affinity_protein_1d_sequence**(smiles_list: List[str], amino_acid_sequence: str, affinity_model_type: str = "MPNN-CNN") — same DeepPurpose download-on-demand caveat.
- **calculate_physicochemical_properties**(smiles_string: str) — RDKit real physicochemical descriptors. Tier A.
- **analyze_accelerated_stability_of_pharmaceutical_formulations**(formulations: List[dict], storage_conditions: List[dict], time_points: List[int]) — Arrhenius-based accelerated stability. Tier B.
- **run_3d_chondrogenic_aggregate_assay**(chondrocyte_cells: dict, test_compounds: list, culture_duration_days: int = 21, measurement_intervals: int = 7) — protocol generator. Tier A.
- **grade_adverse_events_using_vcog_ctcae**(clinical_data_file: str) — VCOG-CTCAE grading rule table lookup. Tier A.
- **analyze_radiolabeled_antibody_biodistribution**(time_points, tissue_data: dict) — biodistribution/PK profile fit (must include `tumor` key).
- **estimate_alpha_particle_radiotherapy_dosimetry**(biodistribution_data: dict, radiation_parameters: dict, output_file: str = "dosimetry_results.csv") — MIRD-schema dosimetry. Tier B (closed-form formula, real).
- **perform_mwas_cyp2c19_metabolizer_status**(methylation_data_path: str, metabolizer_status_path: str, covariates_path: Optional[str] = None, pvalue_threshold: float = 0.05, output_file: str = "significant_cpg_sites.csv") — CpG-site MWAS regression. Tier B (statsmodels).
- **analyze_xenograft_tumor_growth_inhibition**(data_path: str, time_column: str, volume_column: str, group_column: str, subject_column: str, output_dir: str = "./results") — tumor growth inhibition stats across groups. Tier B.
- **analyze_western_blot**(blot_image_path: str, target_bands: list, loading_control_band: dict, antibody_info: dict, output_dir: str = "./results") — densitometric Western blot quantification. Tier C.

## Categoria: Synthetic biology & systems biology

- **engineer_bacterial_genome_for_therapeutic_delivery**(bacterial_genome_file: str, genetic_parts: dict) — integrate genetic parts (promoters/genes/terminators/cargo) into a genome. Tier A (sequence assembly).
- **analyze_barcode_sequencing_data**(input_file: str, barcode_pattern: Optional[str] = None, flanking_seq_5prime: Optional[str] = None, flanking_seq_3prime: Optional[str] = None, min_count: int = 5, output_dir: str = "./results") — barcode extraction/quantification/lineage. Tier A.
- **analyze_bifurcation_diagram**(time_series_data: ndarray, parameter_values: ndarray, system_name: str = "Dynamical System", output_dir: str = "./") — bifurcation analysis. Tier B.
- **create_biochemical_network_sbml_model**(reaction_network: List[dict], kinetic_parameters: dict, output_file: str = "biochemical_model.xml") — SBML model generation (`python-libsbml`). Tier A.
- **optimize_codons_for_heterologous_expression**(target_sequence: str, host_codon_usage: dict) — codon-usage optimization. Tier A.
- **simulate_gene_circuit_with_growth_feedback**(circuit_topology: ndarray, kinetic_params: dict, growth_params: dict, simulation_time: float = 100, time_points: int = 1000) — ODE gene circuit + growth feedback. Tier B.
- **identify_fas_functional_domains**(sequence: str, sequence_type: str = "protein", output_file: str = "fas_domains_report.txt") — FAS domain identification. Tier A (simplified pattern/HMM-based, documented as such).
- **perform_flux_balance_analysis**(model_file: str, constraints: Optional[dict] = None, objective_reaction: Optional[str] = None, output_file: str = "fba_results.csv") — real FBA via `cobra`. Tier A.
- **model_protein_dimerization_network**(monomer_concentrations: dict, dimerization_affinities: dict, network_topology: list) — equilibrium dimer concentration solver. Tier B.
- **simulate_metabolic_network_perturbation**(model_file: str, initial_concentrations: dict, perturbation_params: dict, simulation_time: float = 100, time_points: int = 1000) — kinetic metabolic network + perturbation response. Tier B.
- **simulate_protein_signaling_network**(network_structure: dict, reaction_params: dict, species_params: dict, simulation_time: float = 100, time_points: int = 1000) — ODE logic-model signaling network (normalized Hill functions). Tier B.
- **compare_protein_structures**(pdb_file1: str, pdb_file2: str, chain_id1: str = "A", chain_id2: str = "A", output_prefix: str = "protein_comparison") — structural comparison (Biopython/biotite structural alignment, RMSD). Tier A.
- **simulate_renin_angiotensin_system_dynamics**(initial_concentrations: dict, rate_constants: dict, feedback_params: dict, simulation_time: float = 48, time_points: int = 100) — RAS ODE simulation. Tier B.
- **simulate_whole_cell_ode_model**(initial_conditions, parameters: dict, ode_function: Optional[callable] = None, time_span: tuple = (0,100), time_points: int = 1000, method: str = "LSODA") — generic ODE integrator (scipy.integrate.solve_ivp), default example model if none given. Tier B — **this is the generic building block several other ODE tools above should share**, implement first.
- **analyze_in_vitro_drug_release_kinetics**(time_points, concentration_data, drug_name: str = "Drug", total_drug_loaded: Optional[float] = None, output_dir: str = "./") — drug release kinetics fit (zero-order/first-order/Higuchi model comparison). Tier B.

## Categoria: Support tools

- **run_python_repl**(command: str) — execute Python in the sandbox, return output. This is a thin wrapper around the SAME mechanism `SandboxNodeExecutor` already uses (`driver.execute_python_script`) — expose it as a directly-callable MCP tool too, not a new execution path.
- **read_function_source_code**(function_name: str) — `inspect.getsource` for a fully-qualified function name. **Security: allowlist to only modules under `backend/src/infrastructure/tools/` and the DB adapter modules** — must NOT allow arbitrary reflection into app internals (DB credentials helpers, JWT signing code, etc). Reject anything outside the allowlist with a clear error, don't silently no-op.

---

## Cross-cutting notes for Fase 5 agents

- `simulate_whole_cell_ode_model`'s generic ODE integrator should be a shared internal helper —
  `simulate_gene_circuit_with_growth_feedback`, `simulate_metabolic_network_perturbation`,
  `simulate_protein_signaling_network`, `simulate_renin_angiotensin_system_dynamics`,
  `simulate_thyroid_hormone_pharmacokinetics` are all specific parameterizations of the same
  scipy.integrate.solve_ivp pattern — don't reimplement the integrator 6 times.
- Every Tier C image tool needs a documented "general-purpose method, not clinically/publication
  validated" disclaimer in its docstring and its MCP tool description string (visible to whatever
  LLM calls it) — this is a correctness/safety requirement, not optional polish.
- Every Tier D tool's `NotImplementedError` message must name exactly what's missing (checkpoint
  name, GPU requirement, external service) and point at `backend/docs/tools/UNSUPPORTED.md`.
