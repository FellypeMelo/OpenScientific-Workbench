from typing import Any
from uuid import UUID
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.services.numeric_validator import NumericValidator

class AuditArtifactUseCase:
    """
    Application use case for checking artifact consistency and catching float hallucinations.
    """
    def __init__(self, session_repo: SessionRepositoryPort, tolerance: float = 1e-5):
        self.session_repo = session_repo
        self.validator = NumericValidator(tolerance=tolerance)

    async def execute(self, session_id: UUID, generated_data: Any, expected_data: Any) -> bool:
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # Compare structures recursively
        is_valid = self.validator.compare_structures(generated_data, expected_data)
        
        if not is_valid:
            # Transition to rejected state
            session.transition_to("ARTIFACT_REJECTED")
            await self.session_repo.save(session)
            raise ValueError(
                "ERR_NUMERIC_DIVERGENCE: Generated values exceed mathematical tolerance threshold (1e-5)."
            )

        return True
