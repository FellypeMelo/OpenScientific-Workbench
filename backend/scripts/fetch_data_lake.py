"""Best-effort downloader for the data lake (see `data_lake/MANIFEST.md`).

Populates `data_lake/` (repo root, bind-mounted read-only into the backend/
worker containers at `/datalake` -- see `docker-compose.yml` and
`settings.DATA_LAKE_ROOT`) with the reference datasets that have a genuinely
stable, unauthenticated, direct download URL. Everything else in the
manifest requires a registration/license click-through or has no stable
static URL (a versioned filename, a session-generated export link, ...) --
for those this script prints the source page and stops, it does NOT attempt
to script around a login wall or guess a version number.

Run from the repo root:

    python backend/scripts/fetch_data_lake.py [--target DIR]

Idempotent: skips any file that already exists in the target directory.
"""
import argparse
import gzip
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TARGET = _REPO_ROOT / "data_lake"

_USER_AGENT = "OpenScientific-Workbench-data-lake-fetch/1.0"

# (filename, direct URL, decompress-with -- "gzip" or None). One row per
# "auto" entry in data_lake/MANIFEST.md; keep the two files in sync.
_AUTO_DOWNLOADS = [
    (
        "gene_info.csv",
        "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz",
        "gzip",
    ),
    (
        "go-plus.json",
        "http://purl.obolibrary.org/obo/go/extensions/go-plus.json",
        None,
    ),
    (
        "gwas_catalog.tsv",
        "https://www.ebi.ac.uk/gwas/api/search/downloads/alternative",
        None,
    ),
    (
        "variant_table.csv",
        "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz",
        "gzip",
    ),
]

# (filename, source page URL, one-line reason it can't be automated).
_MANUAL_DOWNLOADS = [
    ("proteinatlas.tsv", "https://www.proteinatlas.org/about/download", "zip archive behind a versioned link; download proteinatlas.tsv.zip and extract manually"),
    ("gtex_tissue_gene_tpm.csv", "https://gtexportal.org/home/downloads/adult-gtex/bulk_tissue_expression", "some files require free registration"),
    ("msigdb_human_c1_positional_geneset.csv", "https://www.gsea-msigdb.org/gsea/msigdb", "free registration required (applies to all 10 msigdb_human_* files)"),
    ("mousemine_m1_positional_geneset.csv", "http://www.mousemine.org/mousemine/begin.do", "query/export UI, no single stable static URL (applies to all 6 mousemine_* files)"),
    ("omim.csv", "https://omim.org/downloads", "license agreement required"),
    ("DisGeNET.csv", "https://www.disgenet.org/downloads", "free registration required"),
    ("affinity_capture-ms.csv", "https://downloads.thebiogrid.org/BioGRID", "release version baked into filename/URL, changes every BioGRID release (applies to all 11 BioGRID-derived files)"),
    ("BindingDB_All_202409.tsv", "https://www.bindingdb.org/rwd/bind/chemsearch/marvin/Download.jsp", "usage terms click-through"),
    ("broad_repurposing_hub_molecule_with_smiles.csv", "https://repo-hub.broadinstitute.org/repurposing", "download links generated per-session by the hub UI"),
    ("enamine_cloud_library_smiles.pkl", "https://enamine.net/compound-collections/real-compounds", "commercial catalog, license check needed"),
    ("genebass_pLoF_filtered.pkl", "https://app.genebass.org/downloads", "large files, review terms before downloading"),
    ("marker_celltype.csv", "https://panglaodb.se/markers.html", "pick a source (PanglaoDB or CellMarker), no single canonical stable URL"),
    ("McPAS-TCR.csv", "http://friedmanlab.weizmann.ac.il/McPAS-TCR/", "site requires manual export"),
    ("miRDB_v6.0_results.csv", "http://mirdb.org/download.html", "versioned filename, download page gates on a form"),
    ("miRTarBase_microRNA_target_interaction.csv", "https://mirtarbase.cuhk.edu.cn/", "versioned filename, download page gates on a form"),
    ("Virus-Host_PPI_P-HIPSTER_2020.csv", "https://phipster.org/", "site requires manual export"),
]


def _download(url: str, dest: Path, *, decompress: Optional[str]) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    tmp_path = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, open(tmp_path, "wb") as fh:
        shutil.copyfileobj(response, fh)

    if decompress == "gzip":
        with gzip.open(tmp_path, "rb") as gz_in, open(dest, "wb") as out:
            shutil.copyfileobj(gz_in, out)
        tmp_path.unlink()
    else:
        tmp_path.rename(dest)


def _fetch_czi_census(target: Path) -> None:
    """`czi_census_datasets_v4.csv` -- via the `cellxgene-census` package's
    own stable API rather than a raw URL (see MANIFEST.md)."""
    dest = target / "czi_census_datasets_v4.csv"
    if dest.exists():
        print(f"  [skip] {dest.name} already exists")
        return
    try:
        import cellxgene_census
    except ImportError:
        print(
            "  [manual] czi_census_datasets_v4.csv -- `cellxgene-census` is not "
            "installed in THIS Python environment (it lives in the sandbox "
            "toolkit conda env, backend/sandbox/environment.yml, not the app "
            "venv this script runs in outside a container). Run this script's "
            "czi_census step from inside the sandbox env, or run:\n"
            "      python -c \"import cellxgene_census; "
            "cellxgene_census.open_soma().get('census_info').get('datasets')"
            ".read().concat().to_pandas().to_csv('czi_census_datasets_v4.csv')\""
        )
        return
    census = cellxgene_census.open_soma()
    try:
        df = census["census_info"]["datasets"].read().concat().to_pandas()
        df.to_csv(dest, index=False)
        print(f"  [ok] {dest.name} ({len(df)} rows)")
    finally:
        census.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", type=Path, default=_DEFAULT_TARGET,
        help=f"Directory to populate (default: {_DEFAULT_TARGET})",
    )
    args = parser.parse_args()
    target: Path = args.target
    target.mkdir(parents=True, exist_ok=True)

    print(f"Data lake target: {target}\n")

    print("Automated downloads:")
    for filename, url, decompress in _AUTO_DOWNLOADS:
        dest = target / filename
        if dest.exists():
            print(f"  [skip] {filename} already exists")
            continue
        try:
            _download(url, dest, decompress=decompress)
            print(f"  [ok] {filename}")
        except Exception as exc:  # noqa: BLE001 -- best-effort fetch, report and continue
            print(f"  [FAILED] {filename} <- {url}\n           {exc}", file=sys.stderr)

    _fetch_czi_census(target)

    print("\nManual downloads (see data_lake/MANIFEST.md for the full table):")
    for filename, source_url, reason in _MANUAL_DOWNLOADS:
        dest = target / filename
        status = "already present" if dest.exists() else "MISSING"
        print(f"  [{status}] {filename}\n    source: {source_url}\n    why manual: {reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
