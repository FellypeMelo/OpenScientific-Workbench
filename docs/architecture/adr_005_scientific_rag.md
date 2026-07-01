# ADR 005: RAG Científico (GraphRAG Semântico)
**ID:** ADR-005 | **Status:** Aprovado | **Autor:** Engenheiro de Dados

## 1. Contexto e Problema
Buscas vetoriais clássicas (RAG com cosine similarity) misturam proteínas de nomes similares mas funções opostas (ex: falhas ao cruzar IDs Gene Ontology com Reactome). Isso gera alucinações catastróficas em publicações médicas.

## 2. Alternativas Avaliadas
- **A)** Dense Vector RAG (Qdrant simples, alta taxa de alucinação clínica).
- **B)** **GraphRAG Semântico via Neo4j e BioCypher** (Indexação de entidades com IDs fixos).

## 3. Decisão
Adota-se a **Alternativa B**. O pipeline de ingestão usará o "Marker" para fazer parse de PDFs de Nature/Science e extrair entidades. Essas entidades formarão "Triplos RDF" (Proteína X inibe Enzima Y) atrelados aos seus IDs reais (ex: PDB_ID: 1A2B), armazenados em um banco de grafos Neo4j. A busca vetorial só servirá de filtro inicial (Reranker).

## 4. Consequências
- **Positivo:** "Entity Binding" rígido elimina alucinações e garante referências bibliográficas reais e exatas.
- **Negativo:** Setup do Neo4j eleva requisitos de memória da plataforma. A ingestão de PDFs é mais demorada.
