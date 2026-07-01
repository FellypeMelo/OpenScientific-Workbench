# Limites de Domínio, Restrições e Premissas (Constraints & Assumptions)
**ID Documento:** REQ-DOM-001 | **Status:** Aprovado | **Versão:** 1.0.0

Este documento define os guard-rails organizacionais e os contextos (Bounded Contexts) físicos e matemáticos que balizam a concepção da solução OpenScientific-Workbench (OSW).

## 1. Premissas Arquiteturais (Assumptions)
- **Modelos Proprietários Subotimizados:** Assume-se que o uso contínuo de pipelines complexas em LLMs comerciais com tarifas por token (ex: Claude 3.5) é proibitivo para *long-running computations* (dias de pesquisa); por isso, o OSW é centralizado na otimização de Foundation Models Abertos (ex: DeepSeek-V3).
- **Formatos Científicos Assíncronos:** Processos como a simulação de afinidade no *Boltz-2* não possuem limites precisos de timeout síncrono. Assumimos que tais predições devem rodar de forma completamente *desacoplada* por meio de message brokers (Redis) inter-conectando Clusters HPC via SSH/Slurm.

## 2. Restrições do Sistema (Constraints)
- **Limitação de Acesso ao Host:** A CLI e o servidor Web OSW rodam no host, mas qualquer ferramenta biológica invocada pelo modelo tem permissões de gravação isoladas ao `osw_workspace/`. Tentativas de escrita fora dele gerarão erros de permissão fatais no processo e paralisação imediata da thread do LLM.
- **RAG via Entity Binding (GraphRAG Semântico):** A solução estritamente recusa-se a adotar metodologias de "Dense Vector RAG" de bibliotecas nativas de LangChain que quebram ontologias. É restrição do projeto usar um Grafo de Conhecimento com Triplos RDF para citações médicas exatas, sob risco de corrupção sistêmica (alucinações clínicas).

## 3. Limites de Domínio de Informação Científica
- **Regulamentação (Privacy by Design):** Em conformidade com LGPD (Artigo 14) e as diretrizes do consórcio, metadados PII oriundos do GEO (Gene Expression Omnibus) ou genomas não sanitizados que entrarem no Workspace serão truncados durante uploads de sessão no Revisor de Integridade.
- **Precisão Numérica (Threshold):** Os resultados matemáticos derivados do processamento interno de scripts Python/R declaram sucesso se, e somente se, o limiar de aceitação comparativo entre o manuscrito LLM gerado e o CSV bruto atingir Precisão de Ponto Flutuante Absoluto (Erro Absoluto < 1e-5), conforme `revisor_validation.py`.
