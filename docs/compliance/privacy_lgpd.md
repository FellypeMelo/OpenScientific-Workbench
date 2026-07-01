# Privacidade, Anonimização Genômica (LGPD)
**ID Documento:** ARCH-COMP-001 | **Status:** Aprovado | **Versão:** 1.0.0

A aplicação da IA para biologia molecular lida invariavelmente com PII (Patient Identifiable Information) oriundos de hospitais, exigindo compliance severo à Legislação Geral de Proteção de Dados (LGPD) e Privacy by Design.

## 1. Ciclo de Anonimização Obrigatório (PII Purge)
Arquivos `.vcf`, `.fastq` e genômicos carregados pela UI do OSW no browser não são enviados aos Foundation Models. A execução atua sobre o arquivo em File System, mas cabeçalhos identificáveis DEVERÃO ser removidos por uma Rotina de Ingestão Sanitária (Data Purger) na porta da API Gateway.

## 2. Delegação Tokenizada (LLMs Remotos)
No uso da Orquestração onde chamadas remota são vitais para o Raciocínio (DeepSeek / Qwen remoto):
- **O que vai para a nuvem:** Apenas as assinaturas da ontologia estrutural ou o código fonte gerado abstratamente para Python/R.
- **O que fica confinado:** Sequências genômicas densas, sequenciamentos cruéis do laboratório residem localmente na *Workspace* isolada. A API envia o script, o script roda localmente sobre o genoma, o modelo em núvem avalia *apenas* a estrutura métrica de resultado de saída.

## 3. Retenção e Descarte (Right to be Forgotten)
Conforme LGPD, se um cientista for removido da base Institucional:
- O sistema dispara exclusão total do subvolume CoW (ZFS/Btrfs) que guardava seu fork de Workspace.
- Os logs PostgreSQL de Sessão JSONB atrelados a seu ID são removidos em cascata (`ON DELETE CASCADE`).
