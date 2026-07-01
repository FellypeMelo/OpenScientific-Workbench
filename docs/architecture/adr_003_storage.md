# ADR 003: Persistência de Workspace e Forking via CoW
**ID:** ADR-003 | **Status:** Aprovado | **Autor:** Arquiteto Principal

## 1. Contexto e Problema
Arquivos de bioinformática (como mapeamentos BAM/CRAM de 100GB) são maciços. Se um cientista pedir para o OSW "criar um fork desta conversa para testar um novo limite de alinhamento", copiar 100GB fisicamente é insustentável.

## 2. Alternativas Avaliadas
- **A)** Cópia física bruta (Hard Copy - esgota o NVMe em minutos).
- **B)** Symlinks temporários (Perigoso, edições em um fork destroem os dados do outro fork).
- **C)** **Sistemas de Arquivo Copy-on-Write (Btrfs / ZFS)**.

## 3. Decisão
Adotou-se a **Alternativa C (Btrfs/ZFS)** como formato obrigatório para o volume de dados da plataforma OSW. Quando um *Fork* semântico acontece na interface, o sistema emite um comando de Snapshot ZFS/Btrfs em milissegundos.

## 4. Consequências
- **Positivo:** Bifurcação instantânea O(1). Ocupa 0 bytes adicionais até que uma modificação efetiva (escrita diferencial) seja feita no arquivo.
- **Negativo:** Exige formatação em nível de Sistema Operacional subjacente na Workstation (Linux Btrfs/ZFS nativo), inviabilizando uso de sistemas de arquivo NTFS puros (Windows precisará de WSL2 ext4/Btrfs).
