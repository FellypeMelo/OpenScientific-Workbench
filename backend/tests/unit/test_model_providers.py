import pytest
import os
from src.infrastructure.llm.model_client_factory import ModelClientFactory, DeepSeekClient, ZhipuGLMClient, AnthropicClaudeClient, OpenAIClient

def test_factory_raises_value_error_if_key_missing():
    # Make sure env variables are not present
    old_ds_key = os.environ.pop("DEEPSEEK_API_KEY", None)
    
    with pytest.raises(ValueError, match="Missing DEEPSEEK_API_KEY"):
        ModelClientFactory.get_client("deepseek")
        
    if old_ds_key:
        os.environ["DEEPSEEK_API_KEY"] = old_ds_key

def test_factory_returns_correct_client_class():
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ["ZHIPU_GLM_API_KEY"] = "test-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ["OPENAI_API_KEY"] = "test-key"

    client = ModelClientFactory.get_client("deepseek")
    assert isinstance(client, DeepSeekClient)

    client = ModelClientFactory.get_client("glm")
    assert isinstance(client, ZhipuGLMClient)

    client = ModelClientFactory.get_client("claude")
    assert isinstance(client, AnthropicClaudeClient)

    client = ModelClientFactory.get_client("openai")
    assert isinstance(client, OpenAIClient)
