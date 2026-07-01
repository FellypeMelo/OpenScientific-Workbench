from uuid import UUID
from datetime import datetime
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.session_repository import SessionRepositoryPort

class SubmitTaskUseCase:
    """
    Application use case for executing an agentic research task.
    Supports MCTS step-by-step state changes and token budget checks.
    """
    def __init__(self, session_repo: SessionRepositoryPort, default_token_limit: int = 100000):
        self.session_repo = session_repo
        self.default_token_limit = default_token_limit

    async def execute(self, session_id: UUID, task_nl: str) -> AgentSession:
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # 1. Start MCTS Loop - transition state
        session.transition_to("DAG_GENERATION")

        # 2. Token budget check (Coadyuvante a RNF-005)
        # In a real run, this would be computed dynamically. Here we assert it against limit.
        if self.default_token_limit <= 0:
            raise ValueError("FATAL_LLM_BUDGET_EXCEEDED: Token limit is exhausted for this session.")

        # 3. Simulate step execution
        session.transition_to("EXECUTING_SANDBOX")
        
        # 4. Review Step
        session.transition_to("REVIEW_PENDING")
        
        # 5. Lock results
        session.transition_to("SNAPSHOT_TAKEN")
        session.dag_snapshot = {"completed": True, "task": task_nl}
        
        # Update provenance log
        session.provenance_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "execute_task",
            "task": task_nl,
            "status": "success"
        })

        await self.session_repo.save(session)
        return session
