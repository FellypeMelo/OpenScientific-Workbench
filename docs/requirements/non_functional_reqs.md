# Requisitos Não-Funcionais (RNFs)
**ID Documento:** REQ-NF-001 | **Status:** Aprovado | **Versão:** 1.0.0

Este documento dita as diretrizes e exigências sistêmicas que envolvem a operação do OpenScientific-Workbench (OSW). 

## RNFs Sistêmicos e Segurança
| ID | Atributo | Descrição da Exigência (Threshold) |
| :--- | :--- | :--- |
| **RNF-001** | **Segurança: Isolamento** | Todas e quaisquer execuções autônomas originadas pelo LLM DEVEM ser confidenciais à rede anfitriã (host-network), utilizando namespaces isolados via `gVisor`. |
| **RNF-002** | **Segurança: Path Traversal** | O sistema de submissão e ingestão de arquivos (uploads) DEVE suprimir caminhos com `../` aplicando a mitigação resolve estrita (base name extraction), bloqueando o CVE-2026-7398. |
| **RNF-003** | **Segurança: Gerência Segredos** | Credenciais (Chaves OpenAI/DeepSeek, Tokens SSH Slurm) DEVEM ser efêmeras, não logáveis, armazenadas através de protocolos de cofre virtual tipo Vault. |
| **RNF-004** | **Observabilidade** | Todo log de erro (stdout/stderr) saído da sandbox DEVE ser despachado no OpenTelemetry com Span traceado. |
| **RNF-005** | **Privacidade (LGPD/GDPR)** | Dados de exomas humanos manipulados localmente na sandbox DEVEM ter metadados e tags PII sanitizados no upload, não retornando PII no log do histórico. |

## RNFs de Performance e Integridade
| ID | Atributo | Descrição da Exigência (Threshold) |
| :--- | :--- | :--- |
| **RNF-006** | **Reprodutibilidade Estrita** | Os artefatos finais gerados DEVEM incorporar no seu metadado físico as chaves SHA-256 do arquivo `uv.lock` ou hash de `environment.yaml`. |
| **RNF-007** | **Snapshots File System** | Bifurcações (forking) na conversa e workspace DEVEM operar em O(1) de espaço em disco no estado inicial, sendo mandatória a formatação Btrfs/ZFS nativa do OS. |
| **RNF-008** | **Carga VRAM (Modelos Nativos)** | Execução do Foundation Model **Evo 2** DEVE ser capaz de escalar horizontalmente na predição quando o requerimento da análise exceder a VRAM disponível da infra local. |
