"""Variant/clinical-genomics DB adapters (ClinVar/dbSNP/gnomAD/GWAS Catalog/
OpenTargets/cBioPortal), tested against httpx's built-in `MockTransport`
(same pattern `test_bio_direct_adapters.py` uses) so no real network call is
made while still exercising the real HTTP request/response handling logic.
The mocked response bodies below mirror the real shapes each live API
returned when this module was written (see the adapter module's docstring
for the exact endpoints verified)."""
import httpx
import pytest

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.mcp.variant_clinical_db_adapters import (
    VARIANT_CLINICAL_TOOL_NAMES,
    VariantClinicalAdapters,
    VariantClinicalAPIError,
    register_variant_clinical_db_tools,
)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- query_clinvar -----------------------------------------------------------


@pytest.mark.asyncio
async def test_query_clinvar_gene_search_success():
    captured = {}

    def handler(request):
        url = str(request.url)
        if "esearch.fcgi" in url:
            captured["term"] = request.url.params["term"]
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["4867750"]}})
        assert "esummary.fcgi" in url
        captured["ids"] = request.url.params["id"]
        return httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["4867750"],
                    "4867750": {
                        "uid": "4867750",
                        "accession": "VCV004867750",
                        "title": "NM_007294.4(BRCA1):c.3909G>C (p.Leu1303Phe)",
                        "obj_type": "single nucleotide variant",
                        "gene_sort": "BRCA1",
                        "germline_classification": {
                            "description": "Uncertain significance",
                            "review_status": "criteria provided, single submitter",
                        },
                    },
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_clinvar({"gene": "BRCA1"})

    assert captured["term"] == "BRCA1[gene]"
    assert captured["ids"] == "4867750"
    assert result["total_count"] == 1
    assert result["variants"][0]["accession"] == "VCV004867750"
    assert result["variants"][0]["clinical_significance"] == "Uncertain significance"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_clinvar_gene_with_clinical_significance_filter():
    captured = {}

    def handler(request):
        if "esearch.fcgi" in str(request.url):
            captured["term"] = request.url.params["term"]
            return httpx.Response(200, json={"esearchresult": {"idlist": []}})
        return httpx.Response(500)

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_clinvar({"gene": "BRCA1", "clinical_significance": "pathogenic"})

    assert captured["term"] == "BRCA1[gene] AND pathogenic[Clinical_significance]"
    assert result == {
        "query": {"gene": "BRCA1", "term": "BRCA1[gene] AND pathogenic[Clinical_significance]"},
        "total_count": 0,
        "variants": [],
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_query_clinvar_variation_id_normalizes_vcv_accession_and_fetches_directly():
    captured = {}

    def handler(request):
        assert "esummary.fcgi" in str(request.url)
        captured["ids"] = request.url.params["id"]
        return httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["17661"],
                    "17661": {
                        "uid": "17661",
                        "accession": "VCV000017661",
                        "title": "NM_007294.4(BRCA1):c.5266dupC",
                        "obj_type": "Duplication",
                        "gene_sort": "BRCA1",
                        "germline_classification": {"description": "Pathogenic", "review_status": "reviewed"},
                    },
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_clinvar({"variation_id": "VCV000017661"})

    assert captured["ids"] == "17661"
    assert result["query"] == {"variation_id": "VCV000017661"}
    assert result["variants"][0]["clinical_significance"] == "Pathogenic"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_clinvar_missing_args_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'gene'"):
        await adapters.query_clinvar({})
    with pytest.raises(ValueError, match="non-empty 'gene'"):
        await adapters.query_clinvar(None)


@pytest.mark.asyncio
async def test_query_clinvar_variation_id_not_found_raises_api_error():
    client = _client(
        lambda r: httpx.Response(
            200, json={"result": {"uids": [], "error": "Invalid uid 999999999 at position= 0"}}
        )
    )
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="was not found"):
        await adapters.query_clinvar({"variation_id": "999999999"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_clinvar_malformed_summary_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="expected 'result' data"):
        await adapters.query_clinvar({"variation_id": "17661"})
    await client.aclose()


# --- query_dbsnp ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_dbsnp_success_normalizes_rs_prefix():
    captured = {}

    def handler(request):
        captured["id"] = request.url.params["id"]
        captured["db"] = request.url.params["db"]
        return httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["1042522"],
                    "1042522": {
                        "uid": "1042522",
                        "chr": "17",
                        "spdi": "NC_000017.11:7676153:G:A",
                        "fxn_class": "missense_variant",
                        "clinical_significance": "pathogenic,benign",
                        "genes": [{"name": "TP53", "gene_id": "7157"}],
                        "global_mafs": [{"study": "1000Genomes", "freq": "A=0.5/100"}],
                    },
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_dbsnp({"rsid": "rs1042522"})

    assert captured == {"id": "1042522", "db": "snp"}
    assert result["rsid"] == "rs1042522"
    assert result["chromosome"] == "17"
    assert result["genes"] == ["TP53"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_dbsnp_accepts_bare_numeric_id():
    client = _client(
        lambda r: httpx.Response(
            200,
            json={"result": {"uids": ["1042522"], "1042522": {"uid": "1042522", "chr": "17"}}},
        )
    )
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_dbsnp({"rsid": "1042522"})

    assert result["rsid"] == "rs1042522"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_dbsnp_missing_rsid_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'rsid'"):
        await adapters.query_dbsnp({})
    with pytest.raises(ValueError, match="non-empty 'rsid'"):
        await adapters.query_dbsnp(None)


@pytest.mark.asyncio
async def test_query_dbsnp_non_numeric_rsid_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="numeric rsID"):
        await adapters.query_dbsnp({"rsid": "rsABCDEF"})


@pytest.mark.asyncio
async def test_query_dbsnp_unknown_id_raises_api_error():
    client = _client(
        lambda r: httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["999999999999"],
                    "999999999999": {"uid": "999999999999", "error": "cannot get document summary"},
                }
            },
        )
    )
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="was not found"):
        await adapters.query_dbsnp({"rsid": "rs999999999999"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_dbsnp_malformed_body_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="expected summary data"):
        await adapters.query_dbsnp({"rsid": "rs1042522"})
    await client.aclose()


# --- retry behavior (exercised via query_dbsnp's single GET) -----------------


@pytest.mark.asyncio
async def test_transient_503_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            json={"result": {"uids": ["1042522"], "1042522": {"uid": "1042522", "chr": "17"}}},
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_dbsnp({"rsid": "rs1042522"})

    assert result["chromosome"] == "17"
    assert calls["n"] == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_persistent_500_retries_a_bounded_number_of_times_then_raises():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, text="server error")

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_dbsnp({"rsid": "rs1042522"})
    assert calls["n"] == 3  # MAX_ATTEMPTS -- bounded, not infinite
    await client.aclose()


# --- query_gnomad --------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_gnomad_success():
    captured = {}

    def handler(request):
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "data": {
                    "gene": {
                        "gene_id": "ENSG00000169174",
                        "symbol": "PCSK9",
                        "variants": [
                            {
                                "variant_id": "1-55039765-A-G",
                                "pos": 55039765,
                                "consequence": "5_prime_UTR_variant",
                                "hgvsc": "c.-73A>G",
                                "hgvsp": None,
                                "rsids": ["rs886039835"],
                                "exome": {"ac": 1, "an": 1377594, "af": 7.259e-7},
                                "genome": None,
                            }
                        ],
                    }
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_gnomad({"gene_symbol": "PCSK9"})

    assert b"gnomad_r4" in captured["body"]
    assert b"GRCh38" in captured["body"]
    assert result["gene_symbol"] == "PCSK9"
    assert result["total_variants"] == 1
    assert result["variants"][0]["variant_id"] == "1-55039765-A-G"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gnomad_missing_gene_symbol_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={"data": {}})))

    with pytest.raises(ValueError, match="non-empty 'gene_symbol'"):
        await adapters.query_gnomad({})


@pytest.mark.asyncio
async def test_query_gnomad_invalid_reference_genome_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={"data": {}})))

    with pytest.raises(ValueError, match="GRCh37' or 'GRCh38'"):
        await adapters.query_gnomad({"gene_symbol": "PCSK9", "reference_genome": "hg19"})


@pytest.mark.asyncio
async def test_query_gnomad_graphql_errors_raise_api_error():
    client = _client(
        lambda r: httpx.Response(200, json={"errors": [{"message": "Gene 'NOTAGENE' not found"}]})
    )
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="GraphQL errors"):
        await adapters.query_gnomad({"gene_symbol": "NOTAGENE"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gnomad_null_gene_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"data": {"gene": None}}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="no gene data"):
        await adapters.query_gnomad({"gene_symbol": "NOTAGENE"})
    await client.aclose()


# --- query_gwas_catalog --------------------------------------------------------


@pytest.mark.asyncio
async def test_query_gwas_catalog_rsid_success():
    def handler(request):
        assert "singleNucleotidePolymorphisms/rs7329174/associations" in str(request.url)
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "associations": [
                        {
                            "pvalue": 1.0e-8,
                            "orPerCopyNum": 1.26,
                            "riskFrequency": "0.22",
                            "loci": [
                                {
                                    "strongestRiskAlleles": [{"riskAlleleName": "rs7329174-G"}],
                                    "authorReportedGenes": [{"geneName": "ELF1"}],
                                }
                            ],
                            "_links": {"study": {"href": "https://www.ebi.ac.uk/gwas/rest/api/studies/GCST123"}},
                        }
                    ]
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_gwas_catalog({"rsid": "rs7329174"})

    assert result["total_associations"] == 1
    assoc = result["associations"][0]
    assert assoc["risk_alleles"] == ["rs7329174-G"]
    assert assoc["reported_genes"] == ["ELF1"]
    assert assoc["study_href"] == "https://www.ebi.ac.uk/gwas/rest/api/studies/GCST123"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gwas_catalog_rsid_without_prefix_is_normalized():
    def handler(request):
        assert "singleNucleotidePolymorphisms/rs7329174/associations" in str(request.url)
        return httpx.Response(200, json={"_embedded": {"associations": []}})

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_gwas_catalog({"rsid": "7329174"})

    assert result["rsid"] == "rs7329174"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gwas_catalog_disease_trait_success():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "studies": [
                        {
                            "accessionId": "GCST000910",
                            "diseaseTrait": {"trait": "Asthma"},
                            "initialSampleSize": "986 European ancestry cases",
                            "publicationInfo": {
                                "publication": "Eur J Hum Genet",
                                "pubmedId": "21150878",
                                "title": "Association between ORMDL3...",
                            },
                        }
                    ]
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_gwas_catalog({"disease_trait": "asthma"})

    assert captured["params"]["diseaseTrait"] == "asthma"
    assert result["total_studies"] == 1
    assert result["studies"][0]["accession_id"] == "GCST000910"
    assert result["studies"][0]["disease_trait"] == "Asthma"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gwas_catalog_missing_args_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'rsid'"):
        await adapters.query_gwas_catalog({})


@pytest.mark.asyncio
async def test_query_gwas_catalog_rsid_404_raises_api_error():
    client = _client(lambda r: httpx.Response(404, json={"error": "not found"}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="has no record"):
        await adapters.query_gwas_catalog({"rsid": "rsNOTREAL"})
    await client.aclose()


# --- query_opentarget -----------------------------------------------------------


@pytest.mark.asyncio
async def test_query_opentarget_direct_ensembl_id_success():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG00000012048",
                        "approvedSymbol": "BRCA1",
                        "associatedDiseases": {
                            "count": 2,
                            "rows": [
                                {"score": 0.83, "disease": {"id": "MONDO_0007254", "name": "breast cancer"}},
                                {"score": 0.81, "disease": {"id": "Orphanet_145", "name": "HBOC syndrome"}},
                            ],
                        },
                    }
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_opentarget({"ensembl_id": "ENSG00000012048"})

    assert result["approved_symbol"] == "BRCA1"
    assert result["total_associations"] == 2
    assert result["associations"][0]["disease_name"] == "breast cancer"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_opentarget_resolves_gene_symbol_via_search():
    calls = []

    def handler(request):
        body = request.content.decode()
        calls.append(body)
        if "SearchTarget" in body:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "ENSG00000012048", "entity": "target", "name": "BRCA1"},
                                {"id": "ENSG00000267595", "entity": "target", "name": "BRCA1P1"},
                            ]
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG00000012048",
                        "approvedSymbol": "BRCA1",
                        "associatedDiseases": {"count": 0, "rows": []},
                    }
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_opentarget({"gene_symbol": "BRCA1"})

    assert len(calls) == 2
    assert result["ensembl_id"] == "ENSG00000012048"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_opentarget_missing_args_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={"data": {}})))

    with pytest.raises(ValueError, match="non-empty 'ensembl_id'"):
        await adapters.query_opentarget({})


@pytest.mark.asyncio
async def test_query_opentarget_no_search_hits_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"data": {"search": {"hits": []}}}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="no target matching"):
        await adapters.query_opentarget({"gene_symbol": "NOTAGENE"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_opentarget_null_target_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"data": {"target": None}}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="no target record"):
        await adapters.query_opentarget({"ensembl_id": "ENSGNOTREAL"})
    await client.aclose()


# --- query_opentarget_genetics ---------------------------------------------------


@pytest.mark.asyncio
async def test_query_opentarget_genetics_direct_variant_id_success():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "id": "1_154453788_C_T",
                        "rsIds": ["rs4129267"],
                        "chromosome": "1",
                        "position": 154453788,
                        "referenceAllele": "C",
                        "alternateAllele": "T",
                        "mostSevereConsequence": {"label": "intron_variant"},
                        "credibleSets": {
                            "count": 2,
                            "rows": [
                                {
                                    "studyLocusId": "00c812e3",
                                    "study": {"id": "GCST90013534", "traitFromSource": "Rheumatoid arthritis"},
                                },
                                {
                                    "studyLocusId": "00da5628",
                                    "study": {"id": "GCST90501111", "traitFromSource": "Glycoprotein acetyls"},
                                },
                            ],
                        },
                    }
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_opentarget_genetics({"variant_id": "1_154453788_C_T"})

    assert result["rsids"] == ["rs4129267"]
    assert result["most_severe_consequence"] == "intron_variant"
    assert result["total_credible_sets"] == 2
    assert result["credible_sets"][0]["trait"] == "Rheumatoid arthritis"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_opentarget_genetics_resolves_rsid_via_search():
    calls = []

    def handler(request):
        body = request.content.decode()
        calls.append(body)
        if "SearchVariant" in body:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "search": {
                            "hits": [{"id": "1_154453788_C_T", "entity": "variant", "name": "1_154453788_C_T"}]
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "id": "1_154453788_C_T",
                        "rsIds": ["rs4129267"],
                        "chromosome": "1",
                        "position": 154453788,
                        "referenceAllele": "C",
                        "alternateAllele": "T",
                        "mostSevereConsequence": {"label": "intron_variant"},
                        "credibleSets": {"count": 0, "rows": []},
                    }
                }
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_opentarget_genetics({"rsid": "rs4129267"})

    assert len(calls) == 2
    assert result["variant_id"] == "1_154453788_C_T"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_opentarget_genetics_missing_args_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={"data": {}})))

    with pytest.raises(ValueError, match="non-empty 'variant_id'"):
        await adapters.query_opentarget_genetics({})


@pytest.mark.asyncio
async def test_query_opentarget_genetics_null_variant_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"data": {"variant": None}}))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="no variant record"):
        await adapters.query_opentarget_genetics({"variant_id": "1_1_A_T"})
    await client.aclose()


# --- query_cbioportal ------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_cbioportal_study_metadata_success():
    def handler(request):
        assert str(request.url).endswith("/api/studies/msk_impact_2017")
        return httpx.Response(
            200,
            json={
                "studyId": "msk_impact_2017",
                "name": "MSK-IMPACT Clinical Sequencing Cohort (MSK, Nat Med 2017)",
                "allSampleCount": 10945,
            },
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_cbioportal({"study_id": "msk_impact_2017"})

    assert result["study_id"] == "msk_impact_2017"
    assert result["study"]["allSampleCount"] == 10945
    await client.aclose()


@pytest.mark.asyncio
async def test_query_cbioportal_gene_mutations_success():
    captured = {}

    def handler(request):
        url = str(request.url)
        if "/api/genes/" in url:
            return httpx.Response(200, json={"entrezGeneId": 7157, "hugoGeneSymbol": "TP53"})
        assert "/api/molecular-profiles/msk_impact_2017_mutations/mutations" in url
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {
                    "sampleId": "P-0000004-T01-IM3",
                    "proteinChange": "R248W",
                    "mutationType": "Missense_Mutation",
                    "chr": "17",
                }
            ],
        )

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    result = await adapters.query_cbioportal({"study_id": "msk_impact_2017", "gene": "TP53"})

    assert captured["params"]["entrezGeneId"] == "7157"
    assert captured["params"]["sampleListId"] == "msk_impact_2017_all"
    assert result["entrez_gene_id"] == 7157
    assert result["total_mutations"] == 1
    assert result["mutations"][0]["proteinChange"] == "R248W"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_cbioportal_missing_study_id_raises_value_error():
    adapters = VariantClinicalAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'study_id'"):
        await adapters.query_cbioportal({})
    with pytest.raises(ValueError, match="non-empty 'study_id'"):
        await adapters.query_cbioportal(None)


@pytest.mark.asyncio
async def test_query_cbioportal_study_not_found_raises_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="was not found"):
        await adapters.query_cbioportal({"study_id": "not_a_real_study"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_cbioportal_gene_not_found_raises_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="no gene record"):
        await adapters.query_cbioportal({"study_id": "msk_impact_2017", "gene": "NOTAGENE"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_cbioportal_non_list_mutations_raises_api_error():
    def handler(request):
        if "/api/genes/" in str(request.url):
            return httpx.Response(200, json={"entrezGeneId": 7157})
        return httpx.Response(200, json={"error": "malformed"})

    client = _client(handler)
    adapters = VariantClinicalAdapters(client)

    with pytest.raises(VariantClinicalAPIError, match="unexpected mutations response shape"):
        await adapters.query_cbioportal({"study_id": "msk_impact_2017", "gene": "TP53"})
    await client.aclose()


# --- register_variant_clinical_db_tools -------------------------------------------


@pytest.mark.asyncio
async def test_register_variant_clinical_db_tools_registers_all_seven_tools():
    registry = MCPServerRegistry()

    registered = register_variant_clinical_db_tools(registry)

    assert set(registered) == set(VARIANT_CLINICAL_TOOL_NAMES)
    assert len(VARIANT_CLINICAL_TOOL_NAMES) == 7
    assert set(registered).issubset(registry.registry.keys())


@pytest.mark.asyncio
async def test_register_variant_clinical_db_tools_makes_tools_routable():
    def handler(request):
        url = str(request.url)
        if "esummary.fcgi" in url and request.url.params.get("db") == "snp":
            return httpx.Response(
                200,
                json={"result": {"uids": ["1042522"], "1042522": {"uid": "1042522", "chr": "17"}}},
            )
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()
    register_variant_clinical_db_tools(registry, client)

    out = await registry.route("query_dbsnp", {"rsid": "rs1042522"})

    assert "rs1042522" in out
    await client.aclose()
