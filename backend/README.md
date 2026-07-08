# osw-backend

Backend Core for OpenScientific-Workbench: a Clean Architecture / DDD FastAPI
gateway coordinating remote bioinformatics workflows (agent sessions, workspace
forking, HPC/Slurm dispatch, GraphRAG, and LLM streaming).

This file exists primarily as packaging metadata: `pyproject.toml` declares
`readme = "README.md"`, which setuptools requires to be present to build the
project's metadata (`pip install .`, used by `backend/Dockerfile`). See the
root [`README.md`](../README.md) for the full architectural rules and the
package layout under `src/` (`domain/`, `application/`, `infrastructure/`,
`presentation/`).

Local development: see `.env.example` for configuration and
`docs/planning/execution_plan_gap_closure.md` for the phased delivery history.
