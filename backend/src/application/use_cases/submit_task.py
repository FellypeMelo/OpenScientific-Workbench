from uuid import UUID
from datetime import datetime

from src.domain.entities.agent_session import AgentSession
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.services.mcts_orchestrator import MCTSOrchestrator


class SubmitTaskUseCase:
    """Executes an agentic research task by driving the MCTS-over-DAG orchestrator.

    The orchestrator (a domain service wired with an LLM planner + node executor)
    is injected, keeping this use case free of any infrastructure dependency.
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        orchestrator: MCTSOrchestrator,
        default_token_limit: int = 100000,
    ):
        self.session_repo = session_repo
        self.orchestrator = orchestrator
        self.default_token_limit = default_token_limit

    async def execute(self, session_id: UUID, task_nl: str) -> AgentSession:
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # Fast-fail budget guard before spending any tokens.
        if self.default_token_limit <= 0:
            raise ValueError("FATAL_LLM_BUDGET_EXCEEDED: Token limit is exhausted for this session.")

        # 1. Expansion + search: NL task -> resolved DAG of sub-tasks.
        session.transition_to("DAG_GENERATION")
        snapshot = await self.orchestrator.run(task_nl)

        # 2. Execution + review phases (review gate wired in RF-002).
        session.transition_to("EXECUTING_SANDBOX")
        session.transition_to("REVIEW_PENDING")

        # 3. Lock the resolved DAG as this checkpoint's snapshot.
        session.transition_to("SNAPSHOT_TAKEN")
        session.dag_snapshot = snapshot.to_dict()

        session.provenance_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "execute_task",
            "task": task_nl,
            "tokens_spent": snapshot.tokens_spent,
            "status": "success",
        })

        await self.session_repo.save(session)
        return session
