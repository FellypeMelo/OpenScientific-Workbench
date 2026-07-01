import os
from typing import Dict, Any, Generator, AsyncGenerator
from src.domain.ports.model_provider import ModelProviderPort
import httpx

class DeepSeekClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> Generator[str, None, None]:
        # Implementation of token streaming will yield tokens as they arrive
        pass


class ZhipuGLMClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://open.bigmodel.cn/api/paas/v4"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "glm-4",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> Generator[str, None, None]:
        pass


class AnthropicClaudeClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 4096,
            "system": system_instruction,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> Generator[str, None, None]:
        pass


class OpenAIClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> Generator[str, None, None]:
        pass


class ModelClientFactory:
    """
    Factory to construct BYOK clients based on model availability.
    """
    
    @staticmethod
    def get_client(provider_name: str) -> ModelProviderPort:
        provider_name = provider_name.lower()
        
        if provider_name == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("Missing DEEPSEEK_API_KEY in environment variables.")
            return DeepSeekClient(api_key)
            
        elif provider_name in ["glm", "z.ai", "zhipu"]:
            api_key = os.getenv("ZHIPU_GLM_API_KEY")
            if not api_key:
                raise ValueError("Missing ZHIPU_GLM_API_KEY in environment variables.")
            return ZhipuGLMClient(api_key)
            
        elif provider_name in ["claude", "anthropic"]:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("Missing ANTHROPIC_API_KEY in environment variables.")
            return AnthropicClaudeClient(api_key)
            
        elif provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("Missing OPENAI_API_KEY in environment variables.")
            return OpenAIClient(api_key)
            
        else:
            raise ValueError(f"Unsupported model provider: {provider_name}")
