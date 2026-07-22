# DB adapter catalog (Fase 2 source-of-truth)

Transcrito verbatim (nomes + descrições) do catálogo colado pelo usuário na sessão que originou
`docs/planning/` sandbox-toolkit work. Cada entrada vira um `register_<domain>_tools()` em
`backend/src/infrastructure/mcp/`, seguindo o padrão de `bio_direct_adapters.py`
(`BioAPIError`, `httpx.AsyncClient` injetável, `arguments: Optional[Dict[str, Any]]`, testado com
`httpx.MockTransport`). A maioria destes é "natural-language OR direct-endpoint" — aceitar tanto
um `query: str` livre quanto um endpoint/params estruturado é o padrão Biomni original, mas o OSW
NÃO tem o LLM-schema-parsing layer que o Biomni usa para NL->query; adaptar para exigir args
estruturados (accession/id/gene symbol/coords conforme o caso) e documentar isso na docstring de
cada adapter, em vez de fingir suporte a NL que não existe.

3 já implementados (não recriar, só confirmar que continuam registrados):
`get_uniprot_sequence`, `get_pdb_structure`, `get_string_interactions` — `bio_direct_adapters.py`.

## Sequence / structure / domain databases

- **query_uniprot** — Query UniProt REST API (NL or direct endpoint). *(Nota: `get_uniprot_sequence` já cobre o caso "sequência por accession"; `query_uniprot` deve cobrir os outros endpoints UniProt — search, entry-by-field, etc.)*
- **query_alphafold** — Query AlphaFold DB API for protein structure predictions.
- **query_interpro** — Query InterPro REST API (NL or direct endpoint) — protein domains/families.
- **query_pdb** — Query RCSB PDB using NL or direct structured query (search, not file download — `get_pdb_structure` already covers file download).
- **query_pdb_identifiers** — Retrieve detailed data and/or download files for PDB identifiers (batch).
- **query_emdb** — Query the Electron Microscopy Data Bank (EMDB) for 3D macromolecular structures.

## Pathway / interaction / regulatory databases

- **query_kegg** — NL prompt -> structured KEGG API query (pathways, genes, compounds).
- **query_stringdb** — Query STRING protein interaction DB (NL or direct endpoint) — `get_string_interactions` already covers the network-fetch case; this should cover other STRING endpoints.
- **query_reactome** — Query Reactome DB (NL or direct endpoint) — pathway data.
- **query_regulomedb** — Query RegulomeDB (NL or direct variant/coordinate specification) — regulatory annotation of variants.
- **query_jaspar** — Query JASPAR REST API (NL or direct endpoint) — transcription factor binding profiles.
- **region_to_ccre_screen** — Given genomic coordinates, retrieve intersecting candidate cis-regulatory elements (cCREs) (ENCODE SCREEN).
- **get_genes_near_ccre** — Given a cCRE, return the k nearest genes sorted by distance.
- **query_remap** — Query ReMap DB for regulatory elements and transcription factor binding sites.

## Genetic variation / clinical genomics databases

- **query_clinvar** — NL prompt -> structured ClinVar query — clinical variant significance.
- **query_dbsnp** — Query NCBI dbSNP (NL or direct search term).
- **query_gnomad** — Query gnomAD for variants in a gene (NL or direct gene symbol) — population allele frequencies.
- **query_gwas_catalog** — Query the GWAS Catalog API (NL or direct endpoint).
- **query_opentarget_genetics** — Query OpenTargets Genetics API (NL or direct GraphQL query).
- **query_opentarget** — Query OpenTargets Platform API (NL or direct GraphQL query) — target-disease associations.
- **query_cbioportal** — Query cBioPortal REST API (NL or direct endpoint) — cancer genomics data.

## Genome browser / expression databases

- **query_ucsc** — Query UCSC Genome Browser API (NL or direct endpoint).
- **query_ensembl** — Query Ensembl REST API (NL or direct endpoint).
- **query_geo** — Query NCBI Gene Expression Omnibus (NL or direct search term).

## Proteomics / pharmacology databases

- **query_pride** — Query PRIDE (PRoteomics IDEntifications) DB (NL or direct endpoint).
- **query_gtopdb** — Query Guide to PHARMACOLOGY DB (GtoPdb) (NL or direct endpoint).

## Sequence identification

- **blast_sequence** — Identify a DNA sequence via NCBI BLAST, with error handling/timeout management/debugging (NCBIWWW.qblast wrapper, or local `blastn` if installed in sandbox toolkit — decide per Fase 1 availability).

## Taxonomy / ecology / paleontology databases (lower priority, still in scope)

- **query_iucn** — Query the IUCN Red List API (NL or direct endpoint) — species conservation status.
- **query_paleobiology** — Query the Paleobiology Database (PBDB) API (NL or direct endpoint).
- **query_worms** — Query the World Register of Marine Species (WoRMS) REST API (NL or direct endpoint).
- **query_mpd** — Query the Mouse Phenome Database (MPD) for mouse strain phenotype data (NL or direct endpoint access).

## Implementation notes for Fase 2 agents

- Reuse `BioAPIError`, `DEFAULT_TIMEOUT_SECONDS = 30.0` convention, and the `_get`/client-injection
  pattern exactly as in `bio_direct_adapters.py`.
- Split across a handful of files by category above (e.g. `structure_db_adapters.py`,
  `pathway_regulatory_db_adapters.py`, `variant_clinical_db_adapters.py`,
  `expression_browser_db_adapters.py`, `proteomics_pharma_db_adapters.py`,
  `taxonomy_db_adapters.py`), each with its own `register_<file>_tools(registry, client=None) -> List[str]`.
- Several of these need an API key (NCBI Entrez/BLAST works better with an email/API key; some GraphQL
  endpoints may rate-limit harder without one) — add `Optional[str] = None` fields to `Settings`
  following the `DEEPSEEK_API_KEY` convention (see `infrastructure/config.py`), never hardcode a key.
- No retry/backoff exists anywhere in this codebase's HTTP adapters today (confirmed gap) — add a
  small shared retry helper (e.g. `httpx` + `tenacity`, or a hand-rolled 2-retry exponential backoff)
  used by all new adapters, since 28 more free-tier public APIs getting hit with zero backoff risks
  429s in real use. Add `tenacity` to `backend/pyproject.toml` if chosen.
- All these are in-process (no sandbox) — pure network I/O, same trust level as the 3 existing ones.
- Test pattern: `httpx.MockTransport`, mirroring `backend/tests/unit/test_bio_direct_adapters.py`
  exactly (success shape, missing/empty required arg -> `ValueError`, upstream 404 -> `BioAPIError`,
  upstream 500 -> propagates `httpx.HTTPStatusError`, malformed body -> `BioAPIError`).
- Wire every new `register_*_tools()` into `get_mcp_registry()` (`presentation/dependencies.py:211`).
