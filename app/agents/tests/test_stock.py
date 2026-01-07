from decimal import Decimal
import os
from typing import Annotated, Any

from agent_framework_azure_ai import AzureAIClient
from azure.identity.aio import DefaultAzureCredential

import pytest
from agent_framework import ai_function, ChatMessage, ChatResponse, ExecutorCompletedEvent, WorkflowOutputEvent
from agent_framework.openai import OpenAIResponsesClient
from pydantic import Field
from zava_shop_shared.models.results import InventoryStatusResult

from zava_shop_agents.stock import RestockResult, StockItem, StockItemCollection, build_workflow


class MockResponsesClient(OpenAIResponsesClient):
    def __init__(self):
        pass

    async def get_response(self, *args, **kwargs):
        if "chat_options" in kwargs:
            if (
                hasattr(kwargs["chat_options"], "response_format")
                and kwargs["chat_options"].response_format == StockItemCollection
            ):
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
    workflow = build_workflow(client=MockResponsesClient(), mcp=mock_mcp)  # pyright: ignore[reportArgumentType]
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


@pytest.fixture
def model_client():
    # Configure the client to use the local AI service
    cred = DefaultAzureCredential()
    assert cred is not None
    client = AzureAIClient(
            credential=cred,
            project_endpoint=os.environ.get("AZURE_AI_PROJECT_ENDPOINT"),
            model_deployment_name=os.environ.get(
                "AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini"
            ),
        )
    return client


@pytest.mark.asyncio
async def test_local_model(model_client):

    @ai_function
    def get_current_inventory_status(
        store_id: Annotated[int, Field(description="Store ID to filter results")] = -1,
        category_name: Annotated[str, Field(description="Category name to filter results")] = "",
        low_stock_threshold: Annotated[int, Field(description="Low stock threshold")] = 10,
    ) -> list[InventoryStatusResult]:
        """
        Get current inventory status across stores with values and low stock alerts.

        Returns inventory levels, cost values, retail values, and low stock alerts
        for products across all stores. Can be filtered by store and category.
        Includes inventory value calculations and stock level warnings.

        Args:
            store_id: Optional store ID to filter results
            category_name: Optional category name to filter results
            low_stock_threshold: Stock level below which to trigger alert (default: 10)

        Returns:
            JSON string with format: {"c": [columns], "r": [[row data]], "n": count}
            Includes store, product, category, stock levels, values, and alerts.

        Example:
            >>> # Get low stock items in Electronics
            >>> result = await get_current_inventory_status(
            >>>     category_name="Electronics",
            >>>     low_stock_threshold=10
            >>> )
            >>> data = json.loads(result)
            >>> low_stock_items = [row for row in data['r']
            >>>                    if row[data['c'].index('low_stock_alert')]]
        """
        assert store_id == 1
        assert low_stock_threshold == 10
        assert not category_name or category_name == "Shoes"
        return [
            InventoryStatusResult(
                is_online=False,
                store_name="Main Street Store",
                sku="SKU123",
                product_name="Product 1",
                product_type="Physical",
                category_name="Category A",
                stock_level=5,
                cost=Decimal("10.0"),
                base_price=Decimal("20.0"),
                retail_value=Decimal("23.0"),
                inventory_value=Decimal("50.0"),
                low_stock_alert=True,
            ),
            InventoryStatusResult(
                is_online=False,
                store_name="Main Street Store",
                sku="SKU122",
                product_name="Product 2",
                product_type="Physical",
                category_name="Category A",
                stock_level=5,
                cost=Decimal("10.0"),
                base_price=Decimal("20.0"),
                retail_value=Decimal("23.0"),
                inventory_value=Decimal("50.0"),
                low_stock_alert=True,
            ),
        ]

    workflow = build_workflow(client=model_client, mcp=[get_current_inventory_status], agent_suffix="-test")  # pyright: ignore[reportArgumentType]
    test_message = ChatMessage(role="user", text="Help me restock store 1")
    result = await workflow.run(test_message)

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
