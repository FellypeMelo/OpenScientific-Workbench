# Data lake manifest

This directory is bind-mounted read-only into the `backend`/`worker` containers at `/datalake`
(`docker-compose.yml`), and from there read-only again into the bwrap sandbox jail
(`backend/src/infrastructure/sandbox/bubblewrap_driver.py`, `settings.DATA_LAKE_ROOT`). Action
tools that need a bundled reference dataset (gene sets, PPI networks, GWAS catalog, ...) read it
from `/datalake/<filename>` at call time.

**Nothing here is bundled in the repo or the Docker image.** Run `backend/scripts/fetch_data_lake.py`
to populate this directory locally. Entries marked "manual" require you to accept a license or log
in on the source site yourself — the script prints the exact URL and stops there, it does not (and
cannot, without violating the source's terms) automate that step.

| File | Source | Access | Notes |
|---|---|---|---|
| `proteinatlas.tsv` | [Human Protein Atlas](https://www.proteinatlas.org/about/download) | auto (direct download, CC BY-SA) | Protein expression across tissues. |
| `gene_info.csv` | [NCBI Gene](https://ftp.ncbi.nlm.nih.gov/gene/DATA/) (`Homo_sapiens.gene_info.gz`) | auto (direct download, public domain) | Comprehensive gene metadata. |
| `go-plus.json` | [Gene Ontology](https://geneontology.org/docs/download-ontology/) (`go-plus.json`, OBO Foundry) | auto (direct download, CC BY 4.0) | GO term graph for functional annotation. |
| `gwas_catalog.tsv` | [NHGRI-EBI GWAS Catalog](https://www.ebi.ac.uk/gwas/docs/file-downloads) (`alternative` download endpoint) | auto (direct download, public domain-equivalent) | GWAS associations. Saved as `.tsv` (not `.pkl` as in the original Biomni catalog) — load with `pandas.read_csv(sep="\t")`; no pickling step needed or attempted. |
| `gtex_tissue_gene_tpm.csv` | [GTEx Portal](https://gtexportal.org/home/downloads/adult-gtex/bulk_tissue_expression) | manual (free registration required for some files) | Tissue-level TPM. |
| `msigdb_human_*_geneset.csv` (10 files: c1-c8, h, plus the GTRD subset) | [MSigDB](https://www.gsea-msigdb.org/gsea/msigdb) | manual (free registration required) | Curated/ontology/hallmark/oncogenic/immunologic/celltype gene sets. |
| `mousemine_*_geneset.csv` (6 files) | [MouseMine](http://www.mousemine.org/mousemine/begin.do) | manual (query/export UI, no single stable static URL) | Mouse gene-set analogues of the MSigDB collections. |
| `omim.csv` | [OMIM](https://omim.org/downloads) | manual (license agreement required) | Genetic disorder <-> gene associations. |
| `DisGeNET.csv` | [DisGeNET](https://www.disgenet.org/downloads) | manual (free registration required) | Gene-disease associations. |
| `affinity_capture-ms.csv`, `affinity_capture-rna.csv`, `co-fractionation.csv`, `dosage_growth_defect.csv`, `genetic_interaction.csv`, `proximity_label-ms.csv`, `reconstituted_complex.csv`, `synthetic_growth_defect.csv`, `synthetic_lethality.csv`, `synthetic_rescue.csv`, `two-hybrid.csv` (11 files) | [BioGRID](https://downloads.thebiogrid.org/BioGRID) (`BIOGRID-ALL-<release>.tab3.zip`, split by `Experimental System` column after download) | manual (release version is baked into the filename/URL and changes every BioGRID release — `fetch_data_lake.py` does not guess it) | Interaction/genetic-interaction evidence tables, one file per experimental system. |
| `BindingDB_All_202409.tsv` | [BindingDB](https://www.bindingdb.org/rwd/bind/chemsearch/marvin/Download.jsp) | manual (usage terms click-through) | Protein-small-molecule binding affinities. |
| `broad_repurposing_hub_molecule_with_smiles.csv`, `broad_repurposing_hub_phase_moa_target_info.csv` | [Broad Drug Repurposing Hub](https://repo-hub.broadinstitute.org/repurposing) | manual (download links are generated per-session by the hub UI, no stable static URL) | Repurposing candidate molecules + MOA/target/phase metadata. |
| `enamine_cloud_library_smiles.pkl` | [Enamine REAL](https://enamine.net/compound-collections/real-compounds) | manual (commercial catalog, license check needed) | Virtual screening library SMILES. |
| `czi_census_datasets_v4.csv` | [CZ CELLxGENE Census](https://chanzuckerberg.github.io/cellxgene-census/) | auto (via the `cellxgene-census` pip package's stable `open_soma()`/`census_info.datasets` API, CC0) | Dataset index for the Cell Census. |
| `genebass_pLoF_filtered.pkl`, `genebass_missense_LC_filtered.pkl`, `genebass_synonymous_filtered.pkl` | [GeneBass](https://app.genebass.org/downloads) | manual (large files, review terms) | Filtered exome variant burden results by consequence class. |
| `marker_celltype.csv` | [PanglaoDB](https://panglaodb.se/markers.html) or [CellMarker](http://xteam.xbio.top/CellMarker/) | manual (pick one source, no single canonical stable URL) | Cell-type marker gene panel. |
| `McPAS-TCR.csv` | [McPAS-TCR](http://friedmanlab.weizmann.ac.il/McPAS-TCR/) | manual (site requires manual export) | TCR sequence/specificity data. |
| `miRDB_v6.0_results.csv` | [miRDB](http://mirdb.org/download.html) | manual (versioned filename, download page gates on a form) | Predicted microRNA targets. |
| `miRTarBase_microRNA_target_interaction.csv`, `miRTarBase_microRNA_target_interaction_pubmed_abtract.txt`, `miRTarBase_MicroRNA_Target_Sites.csv` | [miRTarBase](https://mirtarbase.cuhk.edu.cn/) | manual (versioned filename, download page gates on a form) | Validated microRNA-target interactions + binding sites + source abstracts. |
| `variant_table.csv` | [ClinVar](https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/) (`variant_summary.txt.gz`) | auto (direct download, public domain) | Annotated variant table (distinct from the live `query_clinvar` DB adapter — this is a static local snapshot for offline joins). |
| `Virus-Host_PPI_P-HIPSTER_2020.csv` | [P-HIPSTER](https://phipster.org/) | manual (site requires manual export) | Virus-host protein interactions. |

## Auto vs. manual

"auto" = `fetch_data_lake.py` downloads it directly, no login. "manual" = the script prints the exact
URL + a one-line reason (registration/license/export-only), then skips it — you fetch it yourself
and drop it in this directory with the filename from the table above.
