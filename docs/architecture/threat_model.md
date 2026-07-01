# Modelagem de Ameaças (STRIDE)
**ID Documento:** ARCH-SEC-001 | **Status:** Aprovado | **Versão:** 1.0.0

Este documento reflete a postura de Segurança por Design (Security-by-Design), aplicando a metodologia STRIDE aos componentes críticos do OSW.

## Vetores de Ameaça e Mitigações

| Categoria STRIDE | Descrição da Ameaça no Contexto OSW | Risco (FAIR) | Mecanismo de Mitigação (OSW Architecture) |
| :--- | :--- | :--- | :--- |
| **Spoofing** (Falsificação) | LLM finge ser o administrador root para executar comandos Sudo na sandbox gVisor. | **Alto** | A execução do Docker é estritamente *Rootless* (User Namespace Remapping ID 10001). A tag `--security-opt no-new-privileges` impede qualquer elevação (su/sudo). |
| **Tampering** (Adulteração) | Modificação maliciosa ou corrupção de resultados numéricos pós-geração pelo LLM. | **Crítico** | Assinatura Hashing: Todo arquivo `.csv` final recebe um hash SHA-256 e tem os Lockfiles `uv.lock` bloqueados em read-only pelo CoW Snapshot. |
| **Repudiation** (Repúdio) | Cientista não consegue provar quem modificou o pipeline genômico (usuário ou o agente AI). | **Médio** | Logging OpenTelemetry total e Proveniência Criptográfica JSON: O histórico do PydanticAI guarda o prompt e a decisão do Agente Revisor. |
| **Information Disclosure** | Vulnerabilidade **CVE-2026-7398** (Path Traversal no upload) expõe arquivos `/etc/shadow` do laboratório à API. | **Crítico** | Mitigação no Gateway Central: Sanitização estrita (`os.path.basename`) em uploads. O Sandbox gVisor não tem volume mount para a raiz do host, apenas a pasta restrita. |
| **Denial of Service** | Agente IA entra em loop infinito (MCTS quebrado), gastando todo orçamento de tokens ou esgotando VRAM no cluster Slurm. | **Alto** | Telemetria ativa que corta conexões: Detecção de divergência térmica na GPU, limites de Rate Limiting e quota dura de budget de token por sub-agente PydanticAI. |
| **Elevation of Privilege** | Exploit no SSH do HPC Node permite salto do usuário OSW para SysAdmin do Cluster institucional. | **Médio** | Delegação via Token HashiCorp Vault. Uso de túnel mTLS restrito. A API do Slurm não permite submissões fora da política de cgroups restrita pelo laboratório. |
