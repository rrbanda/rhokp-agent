"""Tests for the LlamaStackAgent (ADK Custom BaseAgent).

Uses mocked AsyncLlamaStackClient so no real Llama Stack, RHOKP, or network
is required. Follows the same mock/patch patterns as test_mcp_server.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from agent.agent import LlamaStackAgent
except ImportError:
    pytest.skip(
        "Agent not importable (missing google-adk or llama-stack-client)",
        allow_module_level=True,
    )


def _make_agent(**overrides) -> LlamaStackAgent:
    defaults = {
        "name": "test_agent",
        "description": "test",
        "llama_stack_url": "http://fake-llama:8080",
        "model_id": "test-model",
        "mcp_server_url": "http://fake-mcp:8010/mcp",
    }
    defaults.update(overrides)
    return LlamaStackAgent(**defaults)


def _make_ctx(user_text: str | None = "How do I install OpenShift?") -> MagicMock:
    """Build a mock InvocationContext with a single user event."""
    ctx = MagicMock()
    ctx.invocation_id = "inv-123"
    if user_text:
        part = SimpleNamespace(text=user_text)
        content = SimpleNamespace(parts=[part])
        event = SimpleNamespace(author="user", content=content)
        ctx.session.events = [event]
    else:
        ctx.session.events = []
    return ctx


def _make_response(
    output_items: list | None = None,
    output_text: str | None = None,
) -> SimpleNamespace:
    """Build a mock Llama Stack Responses API response object."""
    resp = SimpleNamespace()
    if output_items is not None:
        resp.output = output_items
    elif output_text is not None:
        resp.output = None
        resp.output_text = output_text
    else:
        resp.output = None
    return resp


class _MockStream:
    """Async iterable that yields streaming chunks, simulating Llama Stack."""

    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _make_stream(
    text_deltas: list[str] | None = None,
    tool_items: list | None = None,
    completed_response: SimpleNamespace | None = None,
) -> _MockStream:
    """Build a mock async stream of Llama Stack response chunks."""
    chunks: list[SimpleNamespace] = []
    chunks.append(SimpleNamespace(type="response.created"))
    chunks.append(SimpleNamespace(type="response.in_progress"))

    for item in tool_items or []:
        chunks.append(SimpleNamespace(type="response.output_item.done", item=item))

    if text_deltas:
        chunks.append(SimpleNamespace(type="response.output_item.added"))
        chunks.append(SimpleNamespace(type="response.content_part.added"))
        for delta in text_deltas:
            chunks.append(SimpleNamespace(type="response.output_text.delta", delta=delta))
        chunks.append(SimpleNamespace(type="response.content_part.done"))
        chunks.append(SimpleNamespace(type="response.output_item.done", item=None))

    final_resp = completed_response or _make_response(tool_items or [])
    chunks.append(SimpleNamespace(type="response.completed", response=final_resp))
    return _MockStream(chunks)


def _msg_item(text: str, role: str = "assistant") -> SimpleNamespace:
    """Build a response output item of type 'message' with output_text content."""
    return SimpleNamespace(
        type="message",
        role=role,
        content=[SimpleNamespace(type="output_text", text=text)],
    )


def _refusal_item(refusal: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        role="assistant",
        content=[SimpleNamespace(type="refusal", refusal=refusal)],
    )


def _mcp_call_item(
    name: str = "search_red_hat_docs",
    server_label: str = "okp-search",
    output: str = '{"num_found": 1}',
    error: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type="mcp_call",
        name=name,
        server_label=server_label,
        output=output,
        error=error,
    )


def _mcp_list_tools_item(
    server_label: str = "okp-search", tools: list | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        type="mcp_list_tools",
        server_label=server_label,
        tools=tools or ["search_red_hat_docs", "check_okp_health"],
    )


# ---------------------------------------------------------------------------
# _log_tool_traces
# ---------------------------------------------------------------------------


class TestLogToolTraces:
    def test_mcp_call_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        resp = _make_response([_mcp_call_item(output='{"num_found": 5}')])
        with caplog.at_level("INFO", logger="agent.agent"):
            LlamaStackAgent._log_tool_traces(resp)
        assert "search_red_hat_docs" in caplog.text
        assert "okp-search" in caplog.text

    def test_mcp_call_error_warned(self, caplog: pytest.LogCaptureFixture) -> None:
        resp = _make_response([_mcp_call_item(error="Connection refused")])
        with caplog.at_level("WARNING", logger="agent.agent"):
            LlamaStackAgent._log_tool_traces(resp)
        assert "Connection refused" in caplog.text

    def test_mcp_list_tools_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        resp = _make_response([_mcp_list_tools_item()])
        with caplog.at_level("INFO", logger="agent.agent"):
            LlamaStackAgent._log_tool_traces(resp)
        assert "okp-search" in caplog.text
        assert "2 tools" in caplog.text

    def test_non_list_output_safe(self) -> None:
        resp = SimpleNamespace(output="not a list")
        LlamaStackAgent._log_tool_traces(resp)

    def test_none_output_safe(self) -> None:
        resp = SimpleNamespace()
        LlamaStackAgent._log_tool_traces(resp)


# ---------------------------------------------------------------------------
# _check_input_shields
# ---------------------------------------------------------------------------


class TestCheckInputShields:
    async def test_no_shields_returns_none(self) -> None:
        agent = _make_agent()
        client = AsyncMock()
        client.shields.list.return_value = SimpleNamespace(data=[])
        result = await agent._check_input_shields(client, "Hello")
        assert result is None

    async def test_shield_allows_input(self) -> None:
        agent = _make_agent()
        client = AsyncMock()
        shield = SimpleNamespace(identifier="input_safety", provider_resource_id="safety-v1")
        client.shields.list.return_value = SimpleNamespace(data=[shield])
        client.moderations.create.return_value = SimpleNamespace(
            results=[SimpleNamespace(flagged=False)]
        )
        result = await agent._check_input_shields(client, "How to install RHEL?")
        assert result is None
        client.moderations.create.assert_called_once()

    async def test_shield_blocks_input(self) -> None:
        agent = _make_agent()
        client = AsyncMock()
        shield = SimpleNamespace(identifier="input_guard", provider_resource_id="guard-v1")
        client.shields.list.return_value = SimpleNamespace(data=[shield])
        client.moderations.create.return_value = SimpleNamespace(
            results=[SimpleNamespace(flagged=True)]
        )
        result = await agent._check_input_shields(client, "bad input")
        assert result is not None
        assert "safety" in result.lower()

    async def test_output_shield_skipped(self) -> None:
        agent = _make_agent()
        client = AsyncMock()
        shield = SimpleNamespace(identifier="output_safety", provider_resource_id="out-v1")
        client.shields.list.return_value = SimpleNamespace(data=[shield])
        result = await agent._check_input_shields(client, "Hello")
        assert result is None
        client.moderations.create.assert_not_called()

    async def test_shields_list_exception_returns_none(self) -> None:
        agent = _make_agent()
        client = AsyncMock()
        client.shields.list.side_effect = Exception("Network error")
        result = await agent._check_input_shields(client, "Hello")
        assert result is None

    async def test_moderation_exception_continues(self) -> None:
        agent = _make_agent()
        client = AsyncMock()
        shield = SimpleNamespace(identifier="flaky_shield", provider_resource_id="flaky")
        client.shields.list.return_value = SimpleNamespace(data=[shield])
        client.moderations.create.side_effect = Exception("timeout")
        result = await agent._check_input_shields(client, "Hello")
        assert result is None

    async def test_shields_as_raw_list(self) -> None:
        """Handle case where shields.list() returns a plain list (no .data)."""
        agent = _make_agent()
        client = AsyncMock()
        shield = SimpleNamespace(identifier="basic", provider_resource_id="basic-v1")
        client.shields.list.return_value = [shield]
        client.moderations.create.return_value = SimpleNamespace(
            results=[SimpleNamespace(flagged=False)]
        )
        result = await agent._check_input_shields(client, "Hello")
        assert result is None


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    async def test_raises_on_empty_url(self) -> None:
        agent = _make_agent(llama_stack_url="")
        with pytest.raises(ValueError, match="LLAMA_STACK_BASE_URL"):
            await agent._get_client()

    async def test_returns_client(self) -> None:
        agent = _make_agent()
        with patch("agent.agent.AsyncLlamaStackClient") as mock_cls:
            mock_cls.return_value = AsyncMock()
            client = await agent._get_client()
            assert client is not None
            mock_cls.assert_called_once_with(base_url="http://fake-llama:8080")

    async def test_caches_client(self) -> None:
        agent = _make_agent()
        with patch("agent.agent.AsyncLlamaStackClient") as mock_cls:
            mock_cls.return_value = AsyncMock()
            c1 = await agent._get_client()
            c2 = await agent._get_client()
            assert c1 is c2
            mock_cls.assert_called_once()


# ---------------------------------------------------------------------------
# _run_async_impl (integration of all helpers)
# ---------------------------------------------------------------------------


class TestRunAsyncImpl:
    async def test_happy_path_streaming(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx("What is RHEL?")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(
            text_deltas=["RHEL is ", "Red Hat Enterprise Linux."]
        )

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        text_events = [
            e for e in events
            if e.content and e.content.parts
            and e.content.parts[0].text
            and not e.content.parts[0].function_call
        ]
        assert len(text_events) == 1
        assert text_events[0].content.parts[0].text == "RHEL is Red Hat Enterprise Linux."

    async def test_empty_message(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx(None)

        events = [e async for e in agent._run_async_impl(ctx)]

        assert len(events) == 1
        assert "didn't receive" in events[0].content.parts[0].text.lower()

    async def test_shield_blocks(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx("dangerous input")

        mock_client = AsyncMock()
        shield = SimpleNamespace(identifier="input_guard", provider_resource_id="guard")
        mock_client.shields.list.return_value = SimpleNamespace(data=[shield])
        mock_client.moderations.create.return_value = SimpleNamespace(
            results=[SimpleNamespace(flagged=True)]
        )

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        assert len(events) == 1
        assert "safety" in events[0].content.parts[0].text.lower()
        mock_client.responses.create.assert_not_called()

    async def test_llama_stack_error(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx("What is OpenShift?")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.side_effect = Exception("Connection refused")

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        assert len(events) == 1
        assert "error" in events[0].content.parts[0].text.lower()

    async def test_empty_stream_no_text(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx("obscure question")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(text_deltas=[])

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        assert len(events) == 1
        assert "unable to generate" in events[0].content.parts[0].text.lower()

    async def test_tools_passed_to_responses_create(self) -> None:
        agent = _make_agent(mcp_server_url="http://my-mcp:9999/mcp")
        ctx = _make_ctx("test query")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(text_deltas=["answer"])

        with patch.object(agent, "_get_client", return_value=mock_client):
            _ = [e async for e in agent._run_async_impl(ctx)]

        call_kwargs = mock_client.responses.create.call_args.kwargs
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["stream"] is True
        assert call_kwargs["store"] is False
        tools = call_kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "mcp"
        assert tools[0]["server_url"] == "http://my-mcp:9999/mcp"

    async def test_event_metadata(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx("test")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(text_deltas=["response"])

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        text_events = [
            e for e in events
            if e.content and e.content.parts
            and e.content.parts[0].text
            and not e.content.parts[0].function_call
        ]
        assert len(text_events) == 1
        assert text_events[0].author == "test_agent"
        assert text_events[0].invocation_id == "inv-123"
        assert text_events[0].content.role == "model"

    async def test_streaming_with_tool_calls(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx("How to install OpenShift?")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(
            text_deltas=["Here are ", "the steps."],
            tool_items=[_mcp_call_item()],
        )

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        text_events = [
            e for e in events
            if e.content and e.content.parts
            and e.content.parts[0].text
            and not e.content.parts[0].function_call
        ]
        assert len(text_events) == 1
        assert text_events[0].content.parts[0].text == "Here are the steps."

    async def test_tool_call_visible_in_trace(self) -> None:
        """MCP tool calls should produce ADK events with function_call parts."""
        agent = _make_agent()
        ctx = _make_ctx("What is OpenShift?")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(
            text_deltas=["Answer."],
            tool_items=[
                _mcp_call_item(
                    name="search_red_hat_docs",
                    output='{"num_found": 42}',
                )
            ],
        )

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        fc_events = [
            e
            for e in events
            if e.content
            and e.content.parts
            and any(getattr(p, "function_call", None) for p in e.content.parts)
        ]
        assert len(fc_events) == 1
        fc = fc_events[0].content.parts[0].function_call
        assert fc.name == "search_red_hat_docs"

    async def test_stream_error_mid_stream(self) -> None:
        """If streaming fails after some text was accumulated, yield the text."""
        agent = _make_agent()
        ctx = _make_ctx("test")

        class _FailingStream:
            def __init__(self):
                self._yielded = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._yielded:
                    self._yielded = True
                    return SimpleNamespace(type="response.output_text.delta", delta="partial")
                raise RuntimeError("Stream died")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _FailingStream()

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        assert len(events) == 1
        assert events[0].content.parts[0].text == "partial"

    async def test_single_combined_event(self) -> None:
        """All text deltas are combined into one event."""
        agent = _make_agent()
        ctx = _make_ctx("test")

        mock_client = AsyncMock()
        mock_client.shields.list.return_value = SimpleNamespace(data=[])
        mock_client.responses.create.return_value = _make_stream(text_deltas=["hello"])

        with patch.object(agent, "_get_client", return_value=mock_client):
            events = [e async for e in agent._run_async_impl(ctx)]

        text_events = [
            e for e in events
            if e.content and e.content.parts
            and e.content.parts[0].text
            and not e.content.parts[0].function_call
        ]
        assert len(text_events) == 1
        assert text_events[0].content.parts[0].text == "hello"


# ---------------------------------------------------------------------------
# _get_last_user_message
# ---------------------------------------------------------------------------


class TestGetLastUserMessage:
    def test_returns_last_user_text(self) -> None:
        ctx = _make_ctx("Hello world")
        assert LlamaStackAgent._get_last_user_message(ctx) == "Hello world"

    def test_returns_none_for_empty_events(self) -> None:
        ctx = _make_ctx(None)
        assert LlamaStackAgent._get_last_user_message(ctx) is None

    def test_skips_non_user_events(self) -> None:
        part = SimpleNamespace(text="I am the model")
        content = SimpleNamespace(parts=[part])
        model_event = SimpleNamespace(author="model", content=content)

        user_part = SimpleNamespace(text="User question")
        user_content = SimpleNamespace(parts=[user_part])
        user_event = SimpleNamespace(author="user", content=user_content)

        ctx = MagicMock()
        ctx.session.events = [user_event, model_event]
        assert LlamaStackAgent._get_last_user_message(ctx) == "User question"

    def test_returns_latest_when_multiple_user_messages(self) -> None:
        events = []
        for text in ["First question", "Second question"]:
            part = SimpleNamespace(text=text)
            content = SimpleNamespace(parts=[part])
            events.append(SimpleNamespace(author="user", content=content))

        ctx = MagicMock()
        ctx.session.events = events
        assert LlamaStackAgent._get_last_user_message(ctx) == "Second question"

    def test_skips_empty_text_parts(self) -> None:
        empty_part = SimpleNamespace(text="")
        real_part = SimpleNamespace(text="Real message")
        content = SimpleNamespace(parts=[empty_part, real_part])
        event = SimpleNamespace(author="user", content=content)

        ctx = MagicMock()
        ctx.session.events = [event]
        assert LlamaStackAgent._get_last_user_message(ctx) == "Real message"
