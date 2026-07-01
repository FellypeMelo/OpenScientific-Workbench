# Reprodutibilidade Científica (Triplo Snapshot)
**ID Documento:** ARCH-DB-003 | **Status:** Aprovado | **Versão:** 1.0.0

A reprodutibilidade é a premissa máxima da ciência. O OSW assegura determinismo através da **Estratégia de Triplo Snapshot**, cravada em todos os artefatos gerados (imagens, CSVs e arquivos texto) gerados pelo LLM ou pela Sandbox.

## 1. Proveniência de Código (Code Provenance)
- O orquestrador salva cada prompt, decisão de pruning no MCTS e parâmetros estritos em um `osw_provenance.json` injetado no metadado EXIF (se imagem PNG gerada pela UI) ou metadado oculto no arquivo de saída PDF do artigo.

## 2. Proveniência de Ambiente (Environment Provenance)
- O ambiente `gVisor` invoca obrigatoriamente a construção nativa via utilitário `uv`. Todo job de execução força a geração de um hash criptográfico em um arquivo `uv.lock`.
- Se o cientista executar o workflow 5 anos no futuro, as exatas dependências de binários (Python, R, Numpy version) serão puxadas do repositório Pypi por matching de SHA-256.

## 3. Proveniência Física (Physical Snapshotting via Btrfs/ZFS)
- A mecânica de "Fork" do OSW (Ex: "Execute a mesma simulação mas com max_pct_mito=3.0") instrui o OSW File Manager a executar:
  ```bash
  btrfs subvolume snapshot /workspace_1 /workspace_1_fork_A
  ```
- **Consequência O(1):** Zero duplicação de dados, separação instantânea de arquivos brutos RNA-Seq e isolamento total para o Agente prosseguir executando o *fork_A* na sandbox isolada.
