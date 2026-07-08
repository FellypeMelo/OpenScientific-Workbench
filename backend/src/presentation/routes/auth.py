"""
Dev-mode JWT issuance endpoint (Fase 5 - frontend gap closure).

Scope / threat-model note (read before extending this file):
This endpoint is a **dev-mode / demo token issuance shim**, appropriate for a
BYOK (Bring-Your-Own-Key) internal scientific tool where every caller is
already an implicitly-trusted scientist operating their own deployment -- it
is explicitly NOT a production-grade, multi-tenant authentication system.

Concretely:
- `User` (see `src/domain/entities/user.py`) has no password/credential field
  at all, so there is nothing for this endpoint to verify against. It mints a
  valid, signed access token for *any* `user_id`/`iam_role` the caller
  supplies, exactly like the `create_access_token` helper the test suite
  already uses directly (see `presentation/middleware/jwt_auth.py`).
- It exists purely to break the chicken-and-egg problem introduced by Fase 2's
  global `JWTAuthMiddleware`: once every route requires a bearer token,
  *something* must be reachable without one to mint the very first token for
  a legitimate client (the Next.js frontend's `AuthContext`, see
  `frontend/src/lib/auth.ts`).
- Real identity verification (password/OAuth/SSO login, per-user credential
  storage, revocation, refresh-token rotation, etc.) is out of scope here and
  is left as explicit future work -- see Fase 5 in
  `docs/planning/execution_plan_gap_closure.md`.

Do not mistake this for a security boundary: anyone who can reach this route
can mint a token for any `iam_role`, including `admin`. It is safe only
because it is meant to sit behind a trust boundary already assumed by the
rest of this codebase (a single scientist/team's own BYOK deployment), not
because it performs any authorization check of its own.
"""
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel

from src.presentation.middleware.jwt_auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    user_id: UUID
    iam_role: str = "scientist"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def issue_token(request: TokenRequest) -> TokenResponse:
    token = create_access_token(request.user_id, iam_role=request.iam_role)
    return TokenResponse(access_token=token)
