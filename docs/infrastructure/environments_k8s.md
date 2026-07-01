# Ambientes e Orquestração Docker
**ID Documento:** ARCH-INF-002 | **Status:** Aprovado | **Versão:** 1.0.0

Este documento rege a infraestrutura do ambiente de computação que contém os microsserviços do OSW e os nós isolados da Sandbox, mitigando vulnerabilidades.

## 1. Topologia Base do Ambiente (Docker Compose Rootless)
A instalação on-premises padrão adota conteinerização Rootless para os serviços centrais:
- API Gateway
- PostgreSQL, Neo4j, Qdrant
- Redis Broker (Message Queue)

**Isolamento Absoluto da Sandbox:**
O `setup_sandbox.sh` compila e mantém imagens Python 3.12-slim com ferramentas de bioinformática (scanpy, anndata) já atreladas. Ele é instanciado nativamente acoplado ao runtime **gVisor**.

## 2. Kubernetes (K8s) vs Workstations Nativas
Para infraestruturas institucionais, o OSW Core pode rodar em um Cluster Kubernetes, porém a execução da `OSW Sandbox` permanece dependente do agendamento rígido de nós que possuem suporte nativo à virtualização (gVisor KVM runtime-class) e partições que utilizam subvolumes Btrfs para provisionamento CoW (via CSI driver específico).
