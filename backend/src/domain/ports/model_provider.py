from typing import Protocol, Dict, Any, Generator

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

    async def generate_stream(
        self, 
        prompt: str, 
        system_instruction: str, 
        temperature: float = 0.0
    ) -> Generator[str, None, None]:
        """Streams the text response token by token."""
        ...
