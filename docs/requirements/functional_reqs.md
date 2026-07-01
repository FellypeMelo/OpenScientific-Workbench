# Requisitos Funcionais
**ID Documento:** REQ-FUN-001 | **Status:** Aprovado | **Versão:** 1.0.0

Este documento especifica os Requisitos Funcionais (RFs) do sistema, detalhando capacidades sistêmicas mapeadas nas matrizes da plataforma de referência.

## RFs de Orquestração e Agentes
| ID | Descrição do Requisito | Prioridade | Dependências |
| :--- | :--- | :--- | :--- |
| **RF-001** | **Coordenação MCTS:** O sistema DEVE traduzir inputs de linguagem natural num Grafo Direcionado Acíclico (DAG) usando PydanticAI para coordenação de longo horizonte. | Alta | - |
| **RF-002** | **Agente Revisor Crítico:** O sistema DEVE instanciar um loop Ator-Crítico (Actor-Critic) responsável por aprovar outputs baseados em asserções quantitativas (< 1e-5). | Alta | RF-001 |
| **RF-003** | **Persistência de Estados da Sessão:** O sistema DEVE gravar variáveis lógicas e memórias efémeras (Working Memory) num PostgreSQL via JSONB a cada Checkpoint. | Média | RF-001 |

## RFs de Sandbox e Conectores
| ID | Descrição do Requisito | Prioridade | Dependências |
| :--- | :--- | :--- | :--- |
| **RF-004** | **MCP Conectividade Universal:** O sistema DEVE resolver serviços de Biologia (UniProt, PDB, STRING) unicamente via chamadas de ferramentas JSON-RPC padronizadas (BioContextAI / MCPmed). | Alta | - |
| **RF-005** | **Execução rootless gVisor:** O OSW DEVE mapear a invocação de códigos bash, Python, R para execução em uma Docker Sandbox contida por gVisor, mitigando Syscalls não mapeadas. | Máxima | - |
| **RF-006** | **Integração HPC (Slurm):** O sistema DEVE ser capaz de gerar `.sh` (scripts de lote Slurm), transferi-los via túnel Paramiko, executá-los em nós de login remotos e sincronizar arquivos locais de saída. | Alta | RF-005 |

## RFs de Interface Gráfica
| ID | Descrição do Requisito | Prioridade | Dependências |
| :--- | :--- | :--- | :--- |
| **RF-007** | **Componentes WebGL Nativos:** O Frontend (Next.js) DEVE encapsular instâncias in-browser do visualizador **Molstar** para estruturas `.cif` e **IGV.js** para renderizar trilhos genômicos. | Alta | RF-004 |
| **RF-008** | **Editor de Manuscritos Interativo:** A UI DEVE prover renderização LaTeX (Tectonic) instantânea ligada às correções textuais apontadas pelo Revisor Crítico. | Média | RF-002 |

## RFs de Extensibilidade
| ID | Descrição do Requisito | Prioridade | Dependências |
| :--- | :--- | :--- | :--- |
| **RF-009** | **Instalação Semântica de SKILL.md:** O motor DEVE extrair metadados YAML de arquivos de habilidades locais (Skills) e compilá-los com `skill-to-mcp` para torná-los roteáveis pelo Orquestrador. | Alta | - |
