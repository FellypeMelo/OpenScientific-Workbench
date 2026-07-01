# Diretrizes do Design System
**ID Documento:** ARCH-DS-001 | **Status:** Aprovado | **Versão:** 1.0.0

A interface gráfica (Next.js) do OpenScientific-Workbench (OSW) se afasta do layout tradicional de terminal laboratorial. Ela se inspira em painéis modernos de controle de missões, focada em legibilidade e acessibilidade.

## 1. Topologia da Interface (Layout Base)
- **Painel Esquerdo (Orquestração):** Visualização do Grafo DAG MCTS em tempo real, onde o usuário acompanha os ramos de busca (Agentic Search).
- **Painel Central (Editor Científico):** Visualização do Manuscrito renderizado em Markdown/LaTeX simultâneo e Caixa de Chat NL (Natural Language).
- **Painel Direito (Canvas Visual):** Instância desacoplada de WebGL renderizando o estado mutante (como a malha do PDB via Molstar).

## 2. Componentes e Ferramentas Visuais

### Molstar (Mol*) - Renderizador de Biomoléculas
- A interface Next.js importa o Molstar como um WebComponent isolado, conectado à caixa de chat.
- Ao pesquisador enviar `Oculte as cadeias peptídicas Beta`, a UI traduz por baixo para o comando da API visual do Molstar, manipulando o canvas tridimensional em tempo real.

### IGV.js (Trilhas Genômicas)
- Focado na exibição 2D de alinhamento de RNA.
- Componente configurado para lazy-load de arquivos BigWig. Em vez de travar o browser carregando gigabytes de matrizes locais do Btrfs, ele utiliza fetch parcial `Range` headers HTTP da API Gateway.

## 3. Dark Mode Nativo e Cores
O sistema assume `Dark Mode` por predefinição, reduzindo o cansaço ocular de sessões laboratoriais, operando sob uma paleta neutra com destaques orientados a sintaxe (amarelos/laranjas para aminoácidos e verdes para nucleotídeos específicos).
