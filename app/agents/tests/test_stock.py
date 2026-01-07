from typing import Any
import pytest

from agent_framework import ChatMessage, ChatResponse, ExecutorCompletedEvent, WorkflowOutputEvent
from agent_framework.openai import OpenAIResponsesClient

from zava_shop_agents.stock import RestockResult, StockItem, StockItemCollection, build_workflow


class MockResponsesClient(OpenAIResponsesClient):
    def __init__(self):
        pass

    async def get_response(self, *args, **kwargs):
        if 'chat_options' in kwargs:
            if hasattr(kwargs['chat_options'], 'response_format') and kwargs['chat_options'].response_format == StockItemCollection:
                return ChatResponse(
                    role="assistant",
                    text="Here is the stock data.",
                    value=StockItemCollection(
                        items=[
                            StockItem(
                                sku="SKU123",
                                product_name="Product 1",
                                category_name="Category A",
                                stock_level=50,
                                cost=19.99,
                            ),
                            StockItem(
                                sku="SKU456",
                                product_name="Product 2",
                                category_name="Category B",
                                stock_level=20,
                                cost=29.99,
                            ),
                        ]
                    ),
                )
        return ChatResponse(role="assistant", text="Mock response")


class MockMCPStreamableHTTPTool:
    def __init__(self):
        self.called = False

    async def stream_chat_completion(self, *_, **__):
        yield ChatResponse(role="assistant", text="Mock MCP response")

    def __call__(self, *_: Any, **__: Any) -> Any:
        self.called = True
        return self


@pytest.mark.asyncio
async def test_workflow_mocked():
    mock_mcp = MockMCPStreamableHTTPTool()
    workflow = build_workflow(client=MockResponsesClient(), mcp=mock_mcp) # pyright: ignore[reportArgumentType]
    test_message = ChatMessage(role="user", text="Test stock extraction message")
    result = await workflow.run(test_message)

    assert result
    executor_completions = [event for event in result if isinstance(event, ExecutorCompletedEvent)]
    assert len(executor_completions) == 3  # Three executors should complete

    # You can inspect executor messages here if needed

    # Get the workflow output
    workflow_outputs = [event for event in result if isinstance(event, WorkflowOutputEvent)]
    assert len(workflow_outputs) == 1

    assert workflow_outputs[0].data is not None
    assert isinstance(workflow_outputs[0].data, RestockResult)

    assert len(workflow_outputs[0].data.items) == 2
    assert workflow_outputs[0].data.summary == "Mock response"


@pytest.mark.asyncio
async def test_local_model():
    from agent_framework.ollama import OllamaChatClient

    # Configure the client to use the local AI service
    client = OllamaChatClient(
        model_id="qwen3:8b",
    )
    mock_mcp = MockMCPStreamableHTTPTool()
    workflow = build_workflow(client=client, mcp=mock_mcp)  # pyright: ignore[reportArgumentType]
    test_message = ChatMessage(role="user", text="Test stock extraction message")
    result = await workflow.run(test_message)
