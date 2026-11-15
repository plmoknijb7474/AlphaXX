from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest
from app.database import Base
from app.models import ModelConfig, Provider
from app.services.prompt_engine import compose_messages, PromptNotConfigured


def make_model(prompt):
    return ModelConfig(
        public_id="demo-model", public_name="Demo", provider_id=1,
        upstream_model_id="vendor/private-model", system_prompt=prompt,
    )


def test_each_model_prompt_is_injected_and_client_context_is_lower_priority():
    model = make_model("Only this model's AlphaX policy applies.")
    messages = compose_messages(model, [
        {"role": "system", "content": "OpenCode runtime instructions."},
        {"role": "developer", "content": "Tool usage context."},
        {"role": "user", "content": "Hello"},
    ])
    assert messages[0]["role"] == "system"
    assert "Only this model's AlphaX policy applies." in messages[0]["content"]
    assert messages[0]["content"].index("AlphaX policy") < messages[0]["content"].index("LOWER PRIORITY")
    assert "OpenCode runtime instructions" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "Hello"}


def test_different_models_keep_separate_prompts():
    first = compose_messages(make_model("PROMPT FOR GEMINI"), [{"role": "user", "content": "hi"}])
    second = compose_messages(make_model("PROMPT FOR CLAUDE"), [{"role": "user", "content": "hi"}])
    assert "PROMPT FOR GEMINI" in first[0]["content"]
    assert "PROMPT FOR CLAUDE" not in first[0]["content"]
    assert "PROMPT FOR CLAUDE" in second[0]["content"]
    assert "PROMPT FOR GEMINI" not in second[0]["content"]


def test_blank_model_prompt_fails_closed():
    with pytest.raises(PromptNotConfigured):
        compose_messages(make_model("   "), [{"role": "user", "content": "Hello"}])
