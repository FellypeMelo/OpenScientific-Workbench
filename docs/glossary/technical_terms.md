# Glossário de Termos Técnicos e Computacionais
**Status:** Definitivo | **Versão:** 1.0.0

Este documento descreve as tecnologias de infraestrutura, arquitetura de sistemas e segurança subjacentes à operação do OpenScientific-Workbench (OSW).

## Orquestração e Agentes
- **MCP (Model Context Protocol):** Protocolo semântico universal padronizado que atua como tradutor JSON-RPC (via HTTP/SSE ou STDIO) acoplando as capacidades da rede do LLM de forma determinística às ferramentas computacionais isoladas.
- **Agentic Tree Search (MCTS - Monte Carlo Tree Search):** Estratégia de busca de caminhos de execução adotada pelo orquestrador. Permite a delegação hierárquica e "podagem" (pruning) de simulações com erros lógicos sem depender de prompts estritamente lineares.
- **Actor-Critic (Agente Revisor):** Padrão de design implementado pelo Revisor do OSW. O "Ator" (Ator de Geração) escreve o manuscrito ou código; o "Crítico" o audita sintaticamente executando asserções via sandbox.
- **PydanticAI:** Engine framework em Python que gera e interpreta os DAGs (Directed Acyclic Graphs) dinâmicos da plataforma multi-agente, forçando consistência de tipos e limites de contexto entre chamadas de ferramentas.

## Segurança e Isolamento
- **gVisor (runsc):** Hipervisor open-source do Google que opera no nível do espaço de usuário, interceptando todas as chamadas de sistema (syscalls) do kernel host. No OSW, impede travessia de arquivos, injeção de malware e elevação de privilégios.
- **JWT (JSON Web Token) / mTLS:** Mecanismos de segurança e delegação de autoridade. No OSW, garante que as credenciais do cientista não transitem indevidamente pelo LLM, e mTLS firma a autenticação do túnel entre a API Gateway local e os serviços Slurm HPC.
- **HashiCorp Vault / Zero-Trust:** Arquitetura de permissão. Segredos são efémeros, chaves são armazenadas centralmente e autorizadas explicitamente a cada sessão computacional.

## Persistência e Memória
- **Copy-on-Write (CoW) - Btrfs / ZFS:** Modelos de File System empregados pela sandbox OSW. Habilitam a clonagem instântanea (Forking) do diretório de workspace para que ramos paralelos de pesquisa possam ocorrer de forma isolada sem multiplicar os gigabytes de dados no disco rígido.
- **GraphRAG Semântico:** Solução híbrida de Retrieval-Augmented Generation baseada em bases de Grafos (Neo4j). Evita falhas inerentes ao RAG denso espacial, fixando entidades RDF biologicamente precisas (Entity Binding) e extrações processadas por Marker.

## Execução Remota
- **Slurm (HPC):** Agendador líder para computação de alto rendimento. O OSW integra a submissão via um gerador automático paramétrico sobre túnel Paramiko SSH.
- **Modal:** Plataforma de execução em nuvem serverless flutuante de GPUs, suportada pelas ferramentas on-demand no ecossistema OSW.
