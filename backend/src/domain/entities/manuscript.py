from typing import List

from pydantic import BaseModel, Field


class CriticComment(BaseModel):
    """A textual correction raised by the Actor-Critic reviewer (RF-002/RF-008)."""

    id: str
    target_text: str
    suggestion: str
    resolved: bool = False


class ManuscriptDocument(BaseModel):
    """LaTeX manuscript plus the critic comments attached to it (RF-008).

    ``apply_correction`` is the link between the reviewer's output and the editor:
    it rewrites the source and marks the corresponding comment resolved.
    """

    latex_source: str
    comments: List[CriticComment] = Field(default_factory=list)

    def apply_correction(self, comment_id: str, replacement: str) -> None:
        comment = next((c for c in self.comments if c.id == comment_id), None)
        if comment is None:
            raise ValueError(f"No critic comment with id {comment_id!r}.")
        if comment.target_text not in self.latex_source:
            raise ValueError(
                f"Critic comment {comment_id!r} target text is not present in the manuscript."
            )
        self.latex_source = self.latex_source.replace(comment.target_text, replacement, 1)
        comment.resolved = True
