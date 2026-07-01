# ADR 002: Isolamento Estrito via gVisor (runsc)
**ID:** ADR-002 | **Status:** Aprovado | **Autor:** Security Officer

## 1. Contexto e Problema
A execução autônoma de scripts gerados por IA (Agentic Coding) apresenta Risco Crítico (CVE score 10.0 potencial) se o LLM alucinar ou injetar comandos maliciosos no Bash do cientista anfitrião, comprometendo o laboratório inteiro ou os genomas do paciente (LGPD).

## 2. Alternativas Avaliadas
- **A)** Docker Padrão (Vulnerável a syscalls do Kernel e container escapes).
- **B)** Máquinas Virtuais Completas (QEMU/KVM) (Muito lento, overhead > 1GB RAM por job).
- **C)** **Docker Rootless com Runtime gVisor (runsc)**.

## 3. Decisão
Adotou-se a **Alternativa C (gVisor)**. O OSW exigirá que toda ferramenta de terminal (`execute_bash`, `run_python`) rode exclusivamente dentro do contêiner OSW_Sandbox mapeado com o runtime gVisor, que intercepta e isola chamadas de sistema Linux para uma sandox no user-space.

## 4. Consequências
- **Positivo:** Elimina a superfície de ataque ao Kernel (Ring 0) e suprime 99% das técnicas de *Container Escape*.
- **Negativo:** Ligeira degradação de performance I/O (leitura intensa em arquivos muito pequenos), aceitável face à barreira de segurança.
