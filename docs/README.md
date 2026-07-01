# OpenScientific-Workbench (OSW)
## Arquitetura de Referência Aberta e Plataforma de IA para Ciência

**Status:** Produção / Core  
**Licença:** MIT (Conforme diretrizes de código aberto)  
**Versão da Arquitetura:** 1.0.0  

---

### 1. Visão Geral (Executive Summary)
O **OpenScientific-Workbench (OSW)** é um ambiente integrado de execução e orquestração multi-agente projetado para democratizar a biologia computacional e a descoberta científica. Ao encapsular o acesso a mais de 60 bases de dados e ferramentas científicas nativas (como Evo 2, Boltz-2 e scverse), o OSW unifica ambientes de computação de alto desempenho (HPC) e interfaces interativas. 

O diferencial arquitetural do OSW reside na **isolação criptográfica e de processos (gVisor)**, mitigando o risco inerente à geração arbitrária de código por Large Language Models (LLMs), mantendo ao mesmo tempo um ecossistema RAG baseado em grafos (GraphRAG) que suprime falhas de precisão científica e numéricas.

---

### 2. Princípios de Engenharia e Design
Em alinhamento aos rigorosos padrões de arquitetura corporativa da nossa organização, o desenvolvimento do OSW e o design de sua documentação são governados por:
- **Security & Privacy by Design:** Arquitetura Zero-Trust para agentes locais, uso do protocolo Model Context Protocol (MCP) com canais STDIO, proteção contra Path Traversal (CWE-22) e conformidade LGPD.
- **Isolamento de Processos Executáveis:** O "Ator" do sistema (DeepSeek-V3/Qwen) gera abstrações computacionais, cujas submissões são enviadas exclusivamente a containers encapsulados.
- **Agentic Tree Search & Actor-Critic Review:** Procura em árvore via MCTS e loops de correção sincronizados, evitando alucinações matemáticas na compilação de manuscritos científicos.
- **Tolerância a Falhas em HPC:** Bridge paramétrica inteligente com Slurm para Jobs de computação quântica/moleculares remotos.
- **Rastreabilidade Tripla:** Hashing e travamento (lock) do ambiente, código e dados usando criptografia imutável (SHA-256) em arquivos `uv.lock`.

---

### 3. Mapa de Navegação da Documentação

A documentação estruturada do sistema encontra-se hierarquizada nas pastas abaixo. Todas as decisões técnicas possuem Documentos de Decisão de Arquitetura (ADR) ou matrizes de rastreabilidade.

| Diretório | Descrição |
| :--- | :--- |
| **[`/glossary`](./glossary/)** | Dicionários de domínio de negócio científico e terminologia técnica (Modelos, Grafos, etc). |
| **[`/requirements`](./requirements/)** | Visão, escopo, requisitos funcionais e não-funcionais (Performance/Segurança) e rastreabilidade. |
| **[`/architecture`](./architecture/)** | Diagramas C4 (Contexto, Container, Componente, Deploy), ADRs formais e modelagem de ameaças STRIDE. |
| **[`/models`](./models/)** | Modelagem UML de Alto Nível (Contextos Delimitados, Casos de Uso, Sequência e State Machines). |
| **[`/database`](./database/)** | Esquema SQL normalizado, particionamento e políticas de retenção/Btrfs CoW Snapshotting. |
| **[`/api`](./api/)** | Especificações OpenAPI, autenticação JWT, integração MCP e catálogos de erro. |
| **[`/features`](./features/)** | Casos de uso (User Stories), cenários BDD orientados a comportamento. |
| **[`/design`](./design/)** | Design system e guias visuais para o visualizador Molstar (WebGL) e trilhos genômicos IGV.js. |
| **[`/infrastructure`](./infrastructure/)** | Pipelines de CI/CD, clusters de execução Slurm/Modal, SRE, OpenTelemetry, QoS. |
| **[`/standards`](./standards/)** | Guias de desenvolvimento de "Skills", empacotamento, e code-review checks. |
| **[`/planning`](./planning/)** | Roadmap (MVP a Mês 10), gestão de riscos sistêmicos, análise de COCOMO II. |
| **[`/compliance`](./compliance/)** | Matrizes de conformidade LGPD/GDPR, proteção de PII e plano de resposta a incidentes. |

---

### 4. Setup Rápido (Sandbox Segura)
A implementação primária do ambiente seguro de isolamento gVisor para pesquisadores locais requer o pipeline abaixo (para o script completo e seguro de inicialização, consulte o manual de infraestrutura).

```bash
# Provisionamento da Sandbox (Requer Docker e gVisor 'runsc')
chmod +x scripts/setup_sandbox.sh
./scripts/setup_sandbox.sh
```

---
*Documentação gerada de acordo com o REGDOC-013 (Enterprise Architecture Protocol).*
