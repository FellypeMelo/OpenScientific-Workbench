# Padrões de Código e Prompting (Coding Standards)
**ID Documento:** ARCH-STD-001 | **Status:** Aprovado | **Versão:** 1.0.0

Para garantir reprodutibilidade, segurança e uniformidade na extensão da plataforma OSW, engenheiros e cientistas devem seguir regras estritas na escrita do núcleo.

## 1. Padrões de Scripts de Habilidades (Python/R)
- **Bloqueio de Dependências:** Não utilizar bibliotecas genéricas no topo. O ambiente (Conda/uv) atrelado ao código do Habilidade deve ser autossuficiente e possuir um lockfile exato gerado para o runner correspondente.
- **Isolamento de Entrada/Saída:** Todo código Python que grave resultados (ex: outputs de scRNA-seq) no disco *DEVE* usar a constante `$WORKSPACE_DIR` provida pelo OSW, não *hardcoding* caminhos arbitrários locais, falha nisso causará aborto pelo Revisor Revisor gVisor.

## 2. Padrões de Geração de Prompt Sistêmico (System Prompts)
O Orquestrador baseia-se em "Instruções ao Modelo". Para atualizar Prompts:
- **Técnica Chain-of-Thought (CoT):** Obrigue o modelo a estruturar um passo-a-passo `<thought>` em XML explícito antes da extração da resposta JSON.
- **Proibição de Prompting Amplo:** Os Agentes do OSW DEVEM atuar exclusivamente limitados à ontologia médica/científica. Prompts de Agente (ex: Agente Coordenador) devem conter barreiras contra "Context Hijacking".
