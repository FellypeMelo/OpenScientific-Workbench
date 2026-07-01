# Cenários BDD (Gherkin)
**ID Documento:** ARCH-FEAT-002 | **Status:** Aprovado | **Versão:** 1.0.0

Comportamentos fundamentais do OSW descritos em Gherkin, prontos para testes de aceitação ponta-a-ponta (E2E) através de frameworks como Behave/Cypress.

## Cenário 1: Revisor Crítico Detecta Alucinação Numérica (Actor-Critic)
**Funcionalidade:** Validador de Output Científico.

```gherkin
Funcionalidade: Mitigação de Alucinações de Ponto Flutuante

  Cenário: O LLM gera um manuscrito com um número que não consta nos logs brutos
    Dado que a Sandbox finalizou a simulação do Boltz-2 
    E o arquivo bruto "results.csv" marca a afinidade_kd como "-7.8200"
    Quando o Agente Ator gera um manuscrito afirmando: "O plddt e afinidade resultaram em 0.81 e -1.2200"
    E o texto é enviado para a triagem do Agente Revisor
    Então o Revisor detecta que "|-1.2200 - (-7.8200)| > 1e-5"
    E o sistema aborta a renderização do PDF
    E retorna um código de erro "4002 ERR_NUMERIC_DIVERGENCE" ao Ator para re-tentativa.
```

## Cenário 2: Prevenção de Path Traversal
**Funcionalidade:** Segurança da Sandbox Rootless.

```gherkin
Funcionalidade: Bloqueio contra Vulnerabilidades de Path Traversal

  Cenário: MCP tenta gravar arquivo malicioso fora do workspace (CVE-2026-7398)
    Dado que uma Tool do MCP foi instruída pelo modelo a descarregar logs
    Quando o payload emitir a instrução de gravação em "../../etc/passwd_overwrite.txt"
    Então o Gateway da API processa o basename via validação estrita
    E resolve o caminho como "/workspace_autorizado/passwd_overwrite.txt"
    E o gVisor bloqueia acessos a diretórios raiz nativos, falhando qualquer escape.
```
