from typing import Protocol, AsyncGenerator

class ModelProviderPort(Protocol):
    """
    Interface for Bring-Your-Own-Key (BYOK) LLM clients.
    Responsible for routing semantic queries to different providers.
    """

    async def generate_response(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.0
    ) -> str:
        """Sends a text prompt and returns the text response."""
        ...

    # NOTE: declared as a plain `def` (not `async def`) on purpose. Concrete
    # implementations are asynchronous *generator* functions (`async def ...`
    # with `yield` in the body): calling them does not produce a coroutine to
    # `await`, it synchronously returns an `AsyncGenerator` that the caller
    # drives with `async for`. Annotating this Protocol method as `async def`
    # would type it as `Coroutine[..., AsyncGenerator[...]]` (await-then-iterate),
    # which does not match how the implementations actually behave
    # (iterate directly, no `await`). This replaces the previous, incorrect
    # `async def ... -> Generator[str, None, None]` stub, which combined a
    # sync `Generator` return type with an `async def` declaration and never
    # matched any real streaming implementation (all 4 provider clients were
    # `pass`-only stubs).
    def generate_stream(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.0
    ) -> AsyncGenerator[str, None]:
        """Streams the text response token by token as an async generator."""
        ...
