"""RHOKP ADK agent backed by Llama Stack Responses API.

Uses the llama-stack-client SDK to call responses.create() with InputToolMCP
for RHOKP search, following patterns proven in lightspeed-stack.

The agent delegates all agentic orchestration (tool calling, reasoning) to
Llama Stack server-side, keeping the client thin. Optional safety shields
are checked via moderations.create() when registered.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types
from llama_stack_client import AsyncLlamaStackClient
from pydantic import PrivateAttr

from rhokp.logging import bind_request_id

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are a Red Hat expert assistant. You MUST use the search_red_hat_docs "
    "tool to retrieve documentation from the Red Hat Offline Knowledge Portal "
    "before answering ANY question.\n\n"
    "Guidelines:\n"
    "- ALWAYS call search_red_hat_docs first, then answer based on the results.\n"
    "- For introductory questions (e.g. 'What is OpenShift?'), provide a clear "
    "answer grounded in the retrieved documentation.\n"
    "- For technical questions (e.g. installation, troubleshooting, "
    "configuration), ground your answer strictly in the retrieved documentation "
    "and cite source numbers (e.g. [1], [2]).\n"
    "- If the search returns no results, say so and offer to try a different "
    "query. Do not make up information.\n"
    "- Do not fabricate specific version numbers, commands, or configuration "
    "details that are not in the retrieved documentation.\n"
    "- Only answer questions about Red Hat products and technologies.\n"
    "- Always produce a text response after calling the tool. Never return "
    "empty."
)


class LlamaStackAgent(BaseAgent):
    """ADK Custom BaseAgent that delegates to Llama Stack Responses API.

    Passes MCP tools inline via InputToolMCP (no server-side registration
    needed). Optionally runs shield moderation pre-call when shields are
    available on the Llama Stack instance.
    """

    llama_stack_url: str
    model_id: str = "gemini/models/gemini-2.5-pro"
    mcp_server_url: str = "http://localhost:8010/mcp"
    system_instruction: str = SYSTEM_INSTRUCTION

    _client: AsyncLlamaStackClient | None = PrivateAttr(default=None)

    async def _get_client(self) -> AsyncLlamaStackClient:
        if self._client is None:
            if not self.llama_stack_url:
                raise ValueError(
                    "LLAMA_STACK_BASE_URL is required. "
                    "Set it in your environment or agent/.env file."
                )
            self._client = AsyncLlamaStackClient(base_url=self.llama_stack_url)
        return self._client

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        bind_request_id()
        t0 = time.monotonic()

        user_msg = self._get_last_user_message(ctx)
        if not user_msg:
            yield self._text_event(ctx, "I didn't receive a message. Please ask a question.")
            return

        logger.info(
            "Agent invocation start invocation_id=%s model=%s query_len=%d",
            ctx.invocation_id,
            self.model_id,
            len(user_msg),
        )

        client = await self._get_client()

        blocked = await self._check_input_shields(client, user_msg)
        if blocked:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "Agent invocation blocked by shield invocation_id=%s elapsed_ms=%.1f",
                ctx.invocation_id,
                elapsed,
            )
            yield self._text_event(ctx, blocked)
            return

        tools: list[dict[str, Any]] = [
            {
                "type": "mcp",
                "server_label": "okp-search",
                "server_url": self.mcp_server_url,
                "require_approval": "never",
            }
        ]

        logger.info(
            "Calling Llama Stack responses.create model=%s mcp_url=%s",
            self.model_id,
            self.mcp_server_url,
        )
        try:
            stream = await client.responses.create(
                input=user_msg,
                model=self.model_id,
                instructions=self.system_instruction,
                tools=tools,
                stream=True,
                store=False,
            )
        except Exception:
            logger.exception("Llama Stack API error")
            yield self._text_event(
                ctx,
                "I encountered an error connecting to the AI backend. "
                "Please check that the Llama Stack service is available.",
            )
            return

        text_parts: list[str] = []
        pending_mcp_call: dict[str, Any] | None = None
        try:
            async for chunk in stream:
                chunk_type = getattr(chunk, "type", "")

                if chunk_type == "response.output_text.delta":
                    delta = getattr(chunk, "delta", "")
                    if delta:
                        text_parts.append(delta)

                elif chunk_type == "response.mcp_call.in_progress":
                    pending_mcp_call = {
                        "name": getattr(chunk, "name", None),
                        "server_label": getattr(chunk, "server_label", None),
                        "arguments": getattr(chunk, "arguments", None),
                    }

                elif chunk_type == "response.output_item.done":
                    item = getattr(chunk, "item", None)
                    if item:
                        self._log_tool_item(item)
                        event = self._tool_trace_event(ctx, item, pending_mcp_call)
                        if event:
                            yield event
                        if getattr(item, "type", "") == "mcp_call":
                            pending_mcp_call = None

                elif chunk_type == "response.completed":
                    response = getattr(chunk, "response", None)
                    if response:
                        self._log_tool_traces(response)

                elif chunk_type == "response.incomplete":
                    response = getattr(chunk, "response", None)
                    logger.warning(
                        "Llama Stack response incomplete invocation_id=%s",
                        ctx.invocation_id,
                    )
                    if response:
                        self._log_tool_traces(response)
                        self._extract_text_from_response(response, text_parts)

                elif chunk_type == "response.failed":
                    logger.error(
                        "Llama Stack response failed invocation_id=%s",
                        ctx.invocation_id,
                    )

        except Exception:
            logger.exception("Error during Llama Stack streaming")
            if text_parts:
                yield self._text_event(ctx, "".join(text_parts))
            else:
                yield self._text_event(
                    ctx,
                    "I encountered an error connecting to the AI backend. "
                    "Please check that the Llama Stack service is available.",
                )
            return

        elapsed = (time.monotonic() - t0) * 1000
        if text_parts:
            logger.info(
                "Agent invocation complete invocation_id=%s elapsed_ms=%.1f",
                ctx.invocation_id,
                elapsed,
            )
            yield self._text_event(ctx, "".join(text_parts))
        else:
            logger.warning(
                "Agent invocation produced no text invocation_id=%s elapsed_ms=%.1f",
                ctx.invocation_id,
                elapsed,
            )
            yield self._text_event(
                ctx,
                "I was unable to generate a response. Please try rephrasing your question.",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_last_user_message(ctx: InvocationContext) -> str | None:
        """Extract the most recent user message from session events."""
        for event in reversed(ctx.session.events):
            if event.author == "user" and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        return part.text
        return None

    def _text_event(self, ctx: InvocationContext, text: str) -> Event:
        """Create an ADK Event containing a complete text response."""
        return Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model",
                parts=[types.Part(text=text)],
            ),
        )

    @staticmethod
    def _extract_text_from_response(
        response: Any, text_parts: list[str]
    ) -> None:
        """Extract any text from a completed/incomplete response output."""
        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return
        for item in output:
            if getattr(item, "type", "") == "message":
                content = getattr(item, "content", [])
                if isinstance(content, list):
                    for part in content:
                        text = getattr(part, "text", "")
                        if text:
                            text_parts.append(text)

    def _tool_trace_event(
        self,
        ctx: InvocationContext,
        item: Any,
        pending_call: dict[str, Any] | None,
    ) -> Event | None:
        """Create an ADK Event pair for an MCP tool call, visible in the trace.

        Emits a function_call + function_response in a single event so the
        ADK web UI trace panel shows what tool was called and what it returned.
        """
        item_type = getattr(item, "type", "")
        if item_type != "mcp_call":
            return None

        tool_name = getattr(item, "name", "unknown_tool")

        call_args: dict[str, Any] = {}
        raw_args = getattr(item, "arguments", None)
        if raw_args:
            try:
                call_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except (json.JSONDecodeError, TypeError):
                call_args = {"raw": str(raw_args)}
        elif pending_call and pending_call.get("arguments"):
            raw = pending_call["arguments"]
            try:
                call_args = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                call_args = {"raw": str(raw)}

        return Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            name=tool_name,
                            args=call_args,
                        )
                    ),
                ],
            ),
        )

    @staticmethod
    def _log_tool_traces(response: Any) -> None:
        """Log MCP tool call traces from the response for observability."""
        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return

        for item in output:
            item_type = getattr(item, "type", None)
            if item_type == "mcp_call":
                name = getattr(item, "name", "unknown")
                server = getattr(item, "server_label", "unknown")
                error = getattr(item, "error", None)
                if error:
                    logger.warning("MCP tool %s@%s failed: %s", name, server, error)
                else:
                    output_data = getattr(item, "output", "")
                    logger.info(
                        "MCP tool %s@%s returned %d chars",
                        name,
                        server,
                        len(output_data) if output_data else 0,
                    )
            elif item_type == "mcp_list_tools":
                server = getattr(item, "server_label", "unknown")
                tool_list = getattr(item, "tools", [])
                logger.info(
                    "MCP server %s listed %d tools",
                    server,
                    len(tool_list) if tool_list else 0,
                )

    @staticmethod
    def _log_tool_item(item: Any) -> None:
        """Log a single tool-related output item from a streaming response."""
        item_type = getattr(item, "type", "")
        if item_type == "mcp_call":
            name = getattr(item, "name", "unknown")
            server = getattr(item, "server_label", "unknown")
            error = getattr(item, "error", None)
            raw_args = getattr(item, "arguments", None)
            args_summary = ""
            if raw_args:
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if isinstance(parsed, dict):
                        args_summary = " query=%r" % parsed.get("query", "")
                except (json.JSONDecodeError, TypeError):
                    pass

            if error:
                logger.warning(
                    "MCP tool %s@%s failed:%s error=%s", name, server, args_summary, error
                )
            else:
                output_data = getattr(item, "output", "")
                num_found = ""
                if output_data:
                    try:
                        parsed_out = (
                            json.loads(output_data) if isinstance(output_data, str) else output_data
                        )
                        if isinstance(parsed_out, dict) and "num_found" in parsed_out:
                            num_found = " num_found=%s" % parsed_out["num_found"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                logger.info(
                    "MCP tool %s@%s returned %d chars%s%s",
                    name,
                    server,
                    len(output_data) if output_data else 0,
                    args_summary,
                    num_found,
                )
        elif item_type == "mcp_list_tools":
            server = getattr(item, "server_label", "unknown")
            tool_list = getattr(item, "tools", [])
            logger.info(
                "MCP server %s listed %d tools",
                server,
                len(tool_list) if tool_list else 0,
            )

    async def _check_input_shields(
        self, client: AsyncLlamaStackClient, user_msg: str
    ) -> str | None:
        """Run input moderation via Llama Stack shields when available.

        Returns a refusal message if blocked, None if allowed or no shields.
        Follows lightspeed-stack's shield naming convention:
          input_  prefix -> input-only shield
          output_ prefix -> output-only shield (skipped here)
          inout_  prefix -> used for both input and output
          no prefix     -> treated as input shield
        """
        try:
            shields = await client.shields.list()
        except Exception:
            logger.debug("Could not list shields (non-fatal)", exc_info=True)
            return None

        shield_list = getattr(shields, "data", shields) or []
        if not shield_list:
            logger.debug("No shields registered, skipping moderation")
            return None

        for shield in shield_list:
            identifier = getattr(shield, "identifier", "")
            if identifier.startswith("output_"):
                continue

            provider_id = getattr(shield, "provider_resource_id", identifier)
            try:
                result = await client.moderations.create(input=user_msg, model=provider_id)
                results = getattr(result, "results", [])
                if results and getattr(results[0], "flagged", False):
                    logger.warning("Input blocked by shield %s", identifier)
                    return "I cannot process this request due to safety guidelines."
            except Exception:
                logger.warning("Shield %s moderation failed", identifier, exc_info=True)

        return None
