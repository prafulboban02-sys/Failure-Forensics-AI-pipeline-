"""
Shared test fixtures.

Key idea: every pipeline step calls get_llm().invoke(messages) and expects
back an object with .content (str) and .usage_metadata (dict). We fake that
object so tests run in milliseconds, cost nothing, and don't depend on
Ollama/Anthropic being installed or running.
"""

import pytest


class FakeLLMResponse:
    def __init__(self, content: str, input_tokens: int = 10, output_tokens: int = 20):
        self.content = content
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }


class FakeLLM:
    """Drop-in replacement for a LangChain chat model in tests."""
    def __init__(self, response_content: str):
        self._response_content = response_content
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return FakeLLMResponse(self._response_content)


class FakeLLMSequence:
    """Like FakeLLM, but returns a DIFFERENT response on each successive
    invoke() call, cycling through a provided list. Needed to test
    self-consistency / majority-vote logic, which is meaningless to test
    against a single fixed response."""
    def __init__(self, response_contents: list[str]):
        self._responses = response_contents
        self._call_count = 0

    def invoke(self, messages):
        content = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return FakeLLMResponse(content)


@pytest.fixture
def fake_llm_factory():
    """Returns a factory: fake_llm_factory('{"json": "here"}') -> FakeLLM"""
    def _make(response_content: str) -> FakeLLM:
        return FakeLLM(response_content)
    return _make


@pytest.fixture
def fake_llm_sequence_factory():
    """Returns a factory: fake_llm_sequence_factory(['{...}', '{...}']) ->
    FakeLLMSequence, cycling through responses on successive invoke() calls."""
    def _make(response_contents: list[str]) -> FakeLLMSequence:
        return FakeLLMSequence(response_contents)
    return _make
