# Workspace Custom Agent Instructions

This workspace is strictly governed by the custom **Architect Ruleset** (Constitution + Rules Engine) and the **PlantUML Generator** ruleset.

## ⚙️ AI Operational Mandate (Architecture)
Whenever you are assigned any task:
1. **Do not execute blind implementations.** Align with the corresponding Layer rules defined in the custom skill.
2. **Consult the Entry Point:** Go to [SKILL.md](file:///C:/Users/felly/.gemini/config/skills/architect-ruleset/SKILL.md).
3. **Use the Router:** Refer to the **Semantic Task Router** in `SKILL.md` to identify which Layer rules apply.
4. **Strict Hierarchy:** Layer 0 (Constitution) is supreme and overrides all decisions from lower layers.

## 📊 PlantUML Operational Mandate (Modeling)
Whenever you are assigned to create, audit, or improve UML diagrams:
1. **Consult the Entry Point:** Go to [SKILL.md](file:///C:/Users/felly/.gemini/config/skills/plantuml-generator/SKILL.md).
2. **Follow Strict Modeling Rules:** Comply with the 108 strict UML modeling rules for the specific diagram type.
3. **Use the Boilerplate:** Always use the required boilerplate for the diagrams.
4. **Target High Quality:** Aim for Gold or Platinum level on the UML Maturity Scorecard.

## 💻 Cross-Platform Development & Fallback Mandate
1. **Environmental Fallbacks:** Codebases with OS-specific dependencies (e.g., Btrfs, runsc, Vault, Slurm) must implement silent local fallbacks (e.g., `shutil` folder copy, SQLite memory-database, or mock tokens) when run on non-target platforms (e.g., Windows dev machines).
2. **Mock Isolation:** Mocks and mock repositories used for development or dev routers must reside in `src/infrastructure/` and not in `tests/`, ensuring presentation routes never import from tests.
3. **Syntax Hygiene:** Avoid Python-to-TypeScript leakage; ensure string types in TypeScript components are annotated as `string` and not `str`.

