# Histórias de Usuário e Épicos
**ID Documento:** ARCH-FEAT-001 | **Status:** Aprovado | **Versão:** 1.0.0

## Épico 1: Pesquisa Molecular Autônoma
Como um Cientista Principal (PI), eu quero solicitar dobramento de proteínas e predição de afinidade em linguagem natural, para que eu não precise escrever scripts pesados de Bash ou alocar manualmente instâncias de GPUs no cluster da universidade.

### User Stories Associadas
- **US-01 (Chat Interface):** Como usuário, quero escrever "Testar afinidade da proteína X com o ligante Y", para que o Orquestrador MCTS quebre o problema e invocar as bases de dados adequadas.
- **US-02 (Seamless HPC):** Como usuário, eu quero que simulações complexas disparem de forma transparente túneis paramiko para o Slurm, para que eu não perca tempo configurando SSH Nodes.

## Épico 2: Reprodutibilidade e Forking Instantâneo
Como Pesquisador de Dados (Data Scientist), eu quero poder ramificar análises de 50GB no meio do processo, sem duplicar o consumo de disco local do laboratório, para realizar testes "E-se" (What-If Analysis).

### User Stories Associadas
- **US-03 (Btrfs Fork):** Como usuário, quero clicar num botão "Forkar Sessão a partir daqui" no log do chat, para que o sistema execute um CoW Snapshot instantâneo e me dê um canvas de pesquisa novo em milissegundos.
- **US-04 (Lineage Lock):** Como pesquisador, quero que o documento LaTeX final tenha a exata Seed e Lockfile do interpretador embutidas como metadado legível, para garantir que meus pares reproduzam o teste futuramente.
