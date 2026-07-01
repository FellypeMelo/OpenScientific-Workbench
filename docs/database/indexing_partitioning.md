# Estratégia de Indexação e Particionamento
**ID Documento:** ARCH-DB-002 | **Status:** Aprovado | **Versão:** 1.0.0

## 1. Abordagem Híbrida (Hybrid Retrieval)
O OSW armazena grandes volumes de dados textuais e contextuais extraídos de PDFs biológicos, exigindo o particionamento entre bases Vector e Grafos Semânticos (GraphRAG).

### 1.1 Neo4j (Graph Database)
- **Função:** Entity Binding estrito.
- **Estrutura de Indexação:** Nodes particionados por rótulos principais (`Gene`, `Protein`, `Disease`).
- **Índices de Propriedade:** Índice exato (B-Tree) obrigatório nos campos `uniprot_id`, `pdb_id` e `clinvar_id` para coibição de alucinação cruzada.
  ```cypher
  CREATE INDEX index_protein_uniprot IF NOT EXISTS FOR (p:Protein) ON (p.uniprot_id);
  ```

### 1.2 Qdrant (Vector Database)
- **Função:** Similaridade por Embedding HNSW (BGE-M3 Reranker).
- **Particionamento (Multi-Tenancy):** Separação nativa por `Collection` associada ao `workspace_id`.
- **Payload Indexing:** Todo vetor inserido *DEVE* carregar metadados em formato payload com campos indexados para filtrar antes da métrica de similaridade (Ex: filtrar vetores *apenas* se `year > 2020`).

## 2. Retenção e Archiving (S3)
Resultados de simulações em HPC (Arquivos .cif pesados) arquivados em workspaces ociosos há mais de 90 dias passam para armazenamento frio em S3/Glacier, sendo deletados do NVMe primário após extração dos metadados de lineage.
