# Data lake source list (Fase 3 raw input)

Lista verbatim (nome de arquivo + descrição de uma linha) colada pelo usuário — o "data lake" de
tabelas de referência estático que o Biomni paper cita (`Supplementary Table 21-22`, 59 databases,
partly downloaded/pre-processed into pandas DataFrames). Fase 3 usa isto como input pra montar
`backend/data_lake/MANIFEST.md` (cada entrada ganha: URL oficial de origem, licença/termos de uso,
se dá pra automatizar o download em `fetch_data_lake.py` ou se exige conta/login manual).

**Nenhum destes arquivos é baixado por este plano** — mecanismo (setting, bind, manifest, script)
apenas. Ver "Decisões de arquitetura" item 6 do plano.

- `affinity_capture-ms.csv` — Protein-protein interactions detected via affinity capture and mass spectrometry. (BioGRID)
- `affinity_capture-rna.csv` — Protein-RNA interactions detected by affinity capture. (BioGRID)
- `BindingDB_All_202409.tsv` — Measured binding affinities between proteins and small molecules for drug discovery. (BindingDB — usage terms apply)
- `broad_repurposing_hub_molecule_with_smiles.csv` — Molecules from Broad Institute's Drug Repurposing Hub with SMILES annotations.
- `broad_repurposing_hub_phase_moa_target_info.csv` — Drug phases, mechanisms of action, and target information from Broad Institute.
- `co-fractionation.csv` — Protein-protein interactions from co-fractionation experiments. (BioGRID)
- `czi_census_datasets_v4.csv` — Datasets from the Chan Zuckerberg Initiative's Cell Census.
- `DisGeNET.csv` — Gene-disease associations from multiple sources. (DisGeNET — registration required for full access)
- `dosage_growth_defect.csv` — Gene dosage changes affecting growth. (BioGRID)
- `enamine_cloud_library_smiles.pkl` — Compounds from Enamine REAL library with SMILES annotations. (Enamine — commercial catalog, license check needed)
- `genebass_missense_LC_filtered.pkl` — Filtered missense variants from GeneBass.
- `genebass_pLoF_filtered.pkl` — Predicted loss-of-function variants from GeneBass.
- `genebass_synonymous_filtered.pkl` — Filtered synonymous variants from GeneBass.
- `gene_info.csv` — Comprehensive gene information. (NCBI Gene)
- `genetic_interaction.csv` — Genetic interactions between genes. (BioGRID)
- `go-plus.json` — Gene ontology data for functional gene annotations. (Gene Ontology Consortium)
- `gtex_tissue_gene_tpm.csv` — Gene expression (TPM) across human tissues from GTEx. (GTEx — registration for some access tiers)
- `gwas_catalog.pkl` — Genome-wide association studies (GWAS) results. (NHGRI-EBI GWAS Catalog)
- `marker_celltype.csv` — Cell type marker genes for identification.
- `McPAS-TCR.csv` — T-cell receptor sequences and specificity data. (McPAS-TCR)
- `miRDB_v6.0_results.csv` — Predicted microRNA targets from miRDB.
- `miRTarBase_microRNA_target_interaction.csv` — Experimentally validated microRNA-target interactions. (miRTarBase)
- `miRTarBase_microRNA_target_interaction_pubmed_abtract.txt` — PubMed abstracts for miRTarBase interactions.
- `miRTarBase_MicroRNA_Target_Sites.csv` — Binding sites of microRNAs on target genes. (miRTarBase)
- `mousemine_m1_positional_geneset.csv` — Positional gene sets from MouseMine.
- `mousemine_m2_curated_geneset.csv` — Curated gene sets from MouseMine.
- `mousemine_m3_regulatory_target_geneset.csv` — Regulatory target gene sets from MouseMine.
- `mousemine_m5_ontology_geneset.csv` — Ontology-based gene sets from MouseMine.
- `mousemine_m8_celltype_signature_geneset.csv` — Cell type signature gene sets from MouseMine.
- `mousemine_mh_hallmark_geneset.csv` — Hallmark gene sets from MouseMine.
- `msigdb_human_c1_positional_geneset.csv` — Human positional gene sets. (MSigDB — free registration required)
- `msigdb_human_c2_curated_geneset.csv` — Curated human gene sets. (MSigDB)
- `msigdb_human_c3_regulatory_target_geneset.csv` — Regulatory target gene sets. (MSigDB)
- `msigdb_human_c3_subset_transcription_factor_targets_from_GTRD.csv` — TF targets from GTRD/MSigDB.
- `msigdb_human_c4_computational_geneset.csv` — Computationally derived gene sets. (MSigDB)
- `msigdb_human_c5_ontology_geneset.csv` — Ontology-based gene sets. (MSigDB)
- `msigdb_human_c6_oncogenic_signature_geneset.csv` — Oncogenic signatures. (MSigDB)
- `msigdb_human_c7_immunologic_signature_geneset.csv` — Immunologic signatures. (MSigDB)
- `msigdb_human_c8_celltype_signature_geneset.csv` — Cell type signatures. (MSigDB)
- `msigdb_human_h_hallmark_geneset.csv` — Hallmark gene sets. (MSigDB)
- `omim.csv` — Genetic disorders and associated genes. (OMIM — license required for bulk data)
- `proteinatlas.tsv` — Protein expression data. (Human Protein Atlas — CC BY-SA, freely redistributable)
- `proximity_label-ms.csv` — Protein interactions via proximity labeling and mass spectrometry. (BioGRID)
- `reconstituted_complex.csv` — Protein complexes reconstituted in vitro. (BioGRID)
- `synthetic_growth_defect.csv` — Synthetic growth defects from genetic interactions. (BioGRID)
- `synthetic_lethality.csv` — Synthetic lethal interactions. (BioGRID)
- `synthetic_rescue.csv` — Genetic interactions rescuing phenotypes. (BioGRID)
- `two-hybrid.csv` — Protein-protein interactions detected by yeast two-hybrid assays. (BioGRID)
- `variant_table.csv` — Annotated genetic variants table.
- `Virus-Host_PPI_P-HIPSTER_2020.csv` — Virus-host protein-protein interactions. (P-HIPSTER)

## Fase 3 TODO per entry

For each row above, `MANIFEST.md` needs: exact official source URL, license/redistribution terms,
and whether `fetch_data_lake.py` can auto-download it (public direct-download URL, no login) or must
print manual instructions (BioGRID/MSigDB/OMIM/DisGeNET/Enamine/GTEx all gate behind
registration/license click-through — do not attempt to script around that).
