# Pipelines de CI/CD (Continuous Integration & Delivery)
**ID Documento:** ARCH-INF-001 | **Status:** Aprovado | **Versão:** 1.0.0

A entrega contínua do OSW é gerida por GitHub Actions/GitLab CI, assegurando portões de qualidade (Quality Gates) estritos antes do deploy de novas features de AI ou modificações de sandbox.

## 1. Pipeline de Quality Gates (CI)
Todo Pull Request que tente mesclar no branch principal (main) é submetido aos testes abaixo:
1. **Lint e Tipagem Estrita:** MyPy para Python (PydanticAI) e TypeScript Compiler para Next.js.
2. **SAST (Static Application Security Testing):** Varredura SonarQube / Bandit / Trivy focada na detecção de vulnerabilidades de Prompt Injection no código e escapes de gVisor no shell script.
3. **Scan de Contêiner & SBOM:** A imagem Docker gerada do OSW Sandbox passa por um scan de CVEs severos e um SBOM (Software Bill of Materials) é atrelado criptograficamente ao artefato final (Cosign).
4. **Testes Unitários:** O teste matemático validador `revisor_validation.py` deve retornar 100% de cobertura.

## 2. Pipeline de Entrega Contínua (CD)
O artefato final aprovado (Imagem OCI) é enviado ao Registry (GitHub Container Registry / Harbor local) para ser puxado (pulled) pelos ambientes de homologação dos pesquisadores utilizando uma política progressiva (Canary Deploy) sobre nós Docker isolados.
