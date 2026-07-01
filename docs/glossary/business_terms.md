# Glossário de Negócios e Domínio Científico
**Status:** Definitivo | **Versão:** 1.0.0

Este documento descreve os termos do domínio de biologia molecular, genômica e bioinformática aplicados no OpenScientific-Workbench (OSW).

## Modelos Biológicos e Inteligência Artificial
- **Boltz-2:** Modelo open-source (MIT) focado em predição tridimensional de estruturas de proteínas, co-folding complexo e estimativa de afinidade de ligantes (binding affinity). Demonstra performance SOTA equiparada a sistemas comerciais no CASP16.
- **Evo 2:** Foundation Model (DNA) projetado para resolver contextos longos (até 1 milhão de pares de bases), permitindo a predição genômica em nível de single-nucleotide e design de loci completos.
- **ESM3:** Modelo da Meta/Evolutionary Scale Modeling (Community License) que permite o design de sequências, estruturas e funções proteicas de forma multimodal.

## Bibliotecas e Ecossistema
- **scverse (Scanpy/AnnData):** Ecossistema canônico de bibliotecas de bioinformática para análise e controle de qualidade (QC) de sequenciamento de RNA de célula única (scRNA-Seq).
- **Molstar (Mol*):** Componente WebGL2 para visualização tridimensional, renderização e análise exploratória in-browser de complexos proteicos volumosos e mapas de densidade.
- **IGV.js (Integrative Genomics Viewer):** Visualizador de trilhos de navegação que processa arquivos pesados como VCF, BAM e BigWig no lado do cliente.

## Bases de Dados e Ontologias
- **PDB (Protein Data Bank) / mmCIF:** Repositório internacional e formatos de arquivo (.cif) de dados estruturais de macro-moléculas biológicas.
- **UniProt / STRING / GEO / ClinVar:** Principais consórcios globais que fornecem anotações de proteínas funcionais, redes de interação proteína-proteína, expressão gênica e relações patogênicas para validação do RAG científico.
- **BioCypher:** Framework utilizado no OSW para construção transparente do Grafo de Conhecimento (Knowledge Graph), permitindo mapeamentos ontológicos rigorosos via Neo4j.
