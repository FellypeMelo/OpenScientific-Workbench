# Jornadas de UX (UX Journeys)
**ID Documento:** ARCH-DS-002 | **Status:** Aprovado | **Versão:** 1.0.0

O desenho das jornadas de UX foca na experiência de fluxo ininterrupto, lidando graciosamente com o fato de que simulações demoram muitas horas (Long-Running Tasks).

## Jornada A: O Pesquisador e a Simulação Long-Running (HPC)
1. **Intenção (Intent):** Cientista digita um pedido analítico complexo.
2. **Confirmação de Despacho (Dispatch Acknowledgment):** O chat reage instantaneamente, mostrando um painel de estado (Loading Skeleton de Grafo) e avisando: *"Sua tarefa demanda o Boltz-2. O orquestrador requisitou um túnel seguro para o Cluster Slurm"*.
3. **Desengate Ativo (Active Disengagement):** Em vez de travar o navegador com um *spinner* rodando por horas, a sessão migra para a caixa *"Tarefas em Progresso"*. O cientista pode fechar o app OSW.
4. **Alerta Preditivo (Predictive Alerting):** Se a simulação falhar na GPU remotamente por OOM, o MCTS corrige sozinho sem notificar. Ele só enviará uma notificação WebSocket / Push (ou E-mail em cloud environments) na conclusão absoluta com os arquivos .cif baixados no workspace.

## Jornada B: "What-If" Exploration (A Arte do Fork)
1. **Ponto de Retorno:** Ao ler as conclusões de um teste PDB em um nó do log do chat, o cientista decide que deseja rodar um *scanpy* mudando parâmetros de percentual mitocondrial (`max_pct_mito`).
2. **Botão de Bifurcação:** O usuário clica no ícone lateral do bloco de conversa (Branch Node).
3. **Isolamento de Visão:** O UX desenha uma nova thread visual de chat a partir daquele ponto (semelhante ao Git branching UI). O sistema de arquivos (Btrfs Snapshot) copiou 5GB instantaneamente nos bastidores, porém a IU garante que essa troca foi responsiva (< 50ms) sem lag local.
