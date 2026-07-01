# Event Storming e Sagas
**ID Documento:** ARCH-MOD-002 | **Status:** Aprovado | **Versão:** 1.0.0

Mapeamento do fluxo comportamental (Eventos e Comandos) dentro dos fluxos de execução longa do OSW.

## Fluxo Principal: Simulação Molecular Long-Running

| Ator / Sistema | Comando (Command) | Evento Gerado (Domain Event) | Padrão / Política |
| :--- | :--- | :--- | :--- |
| **Cientista** | `SubmitSimulationTask` | `SimulationRequested` | Dispara Orquestrador MCTS. |
| **Coordenador** | `EvaluateTaskComplexity` | `ComplexityEvaluated` | Se Complexo -> Remote HPC; Se Simples -> Local Sandbox. |
| **Coordenador** | `RequestVaultToken` | `SlurmTokenGranted` | Autenticação Vault efêmera (3 min limit). |
| **Integração HPC** | `DispatchSbatch` | `JobQueued_On_Slurm` | Assíncrono (Saga Pattern: MonitorSlurmStatus). |
| **HPC Cluster** | (Execution Finished) | `ExecutionArtifactsReady` | Polling trigger / Webhook. |
| **Sandbox** | `PullRemoteArtifacts` | `ArtifactsSyncedToWorkspace` | File System CoW bloqueia arquivos para leitura. |
| **Revisor Crítico**| `AuditNumericMetrics` | `MetricsPassed_OR_MetricsFailed` | Se Failed -> Compensating Transaction (Nova tentativa LLM). |
| **UI Next.js** | `RenderWebGLArtifact` | `MolstarViewUpdated` | Notifica usuário no Frontend via WebSocket. |
