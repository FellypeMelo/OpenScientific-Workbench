from uuid import UUID
from datetime import datetime

from src.domain.entities.agent_session import AgentSession
from src.domain.ports.reviewer import ReviewerPort
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.services.mcts_orchestrator import MCTSOrchestrator
from src.domain.services.numeric_reviewer import NumericReviewer
from src.domain.services.pii_sanitizer import PIISanitizer


class SubmitTaskUseCase:
    """Executes an agentic research task by driving the MCTS-over-DAG orchestrator
    under a bounded actor-critic review loop.

    Each round: the orchestrator (actor) expands and searches the DAG, then the
    reviewer (critic) gates the result on numeric tolerance (RF-002). A rejected
    result is retried (ARTIFACT_REJECTED -> DAG_GENERATION) up to
    ``max_review_attempts`` times. All collaborators are injected ports/services,
    so the use case stays free of infrastructure.
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        orchestrator: MCTSOrchestrator,
        default_token_limit: int = 100000,
        sanitizer: PIISanitizer = None,
        reviewer: ReviewerPort = None,
        max_review_attempts: int = 3,
    ):
        self.session_repo = session_repo
        self.orchestrator = orchestrator
        self.default_token_limit = default_token_limit
        self.sanitizer = sanitizer or PIISanitizer()
        self.reviewer = reviewer or NumericReviewer()
        self.max_review_attempts = max_review_attempts

    async def execute(self, session_id: UUID, task_nl: str) -> AgentSession:
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # Fast-fail budget guard before spending any tokens.
        if self.default_token_limit <= 0:
            raise ValueError("FATAL_LLM_BUDGET_EXCEEDED: Token limit is exhausted for this session.")

        safe_task = self.sanitizer.sanitize(task_nl)

        while session.dag_generation_attempts < self.max_review_attempts:
            # Actor: expand + search the DAG for this attempt.
            session.transition_to("DAG_GENERATION")
            session.dag_generation_attempts += 1
            snapshot = await self.orchestrator.run(task_nl)

            session.transition_to("EXECUTING_SANDBOX")
            session.transition_to("REVIEW_PENDING")

            # Critic: gate the result on numeric tolerance.
            verdict = await self.reviewer.review(snapshot)
            if verdict.approved:
                session.transition_to("SNAPSHOT_TAKEN")
                session.dag_snapshot = snapshot.to_dict()
                session.provenance_log.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": "execute_task",
                    "task": safe_task,
                    "attempt": session.dag_generation_attempts,
                    "tokens_spent": snapshot.tokens_spent,
                    "status": "success",
                })
                await self.session_repo.save(session)
                return session

            # Rejected: record, persist this checkpoint, then loop back (RF-003).
            session.transition_to("ARTIFACT_REJECTED")
            session.dag_snapshot = snapshot.to_dict()
            session.provenance_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "critic_rejected",
                "task": safe_task,
                "attempt": session.dag_generation_attempts,
                "reason": verdict.reason,
                "status": "rejected",
            })
            # Checkpoint each attempt so state is persisted incrementally, not only
            # once at the very end.
            await self.session_repo.save(session)

        # Exhausted all attempts without approval; session stays ARTIFACT_REJECTED
        # (already persisted by the last loop iteration).
        return session
