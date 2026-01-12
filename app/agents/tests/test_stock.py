from typing import Annotated

from azure.identity.aio import DefaultAzureCredential

import pytest
from agent_framework import ai_function, ChatMessage, ExecutorCompletedEvent, WorkflowOutputEvent
from pydantic import Field

from zava_shop_agents.stock import RestockResult, StockItem, StockItemCollection, build_workflow


@pytest.fixture
def azure_credential():
    # Replace with something else if needed
    return DefaultAzureCredential()


@pytest.mark.asyncio
async def test_simple_path(azure_credential):

    TEST_STOCK = [
                StockItem(
                    sku="SKU123",
                    product_name="Product 1",
                    category_name="Category A",
                    stock_level=5,
                    cost=15.0,
                ),
                StockItem(
                    sku="SKU122",
                    product_name="Product 2",
                    category_name="Category A",
                    stock_level=5,
                    cost=10.0,
                ),
            ]

    @ai_function
    def get_current_inventory_status(
        store_id: Annotated[int, Field(description="Store ID to filter results")] = -1,
        category_name: Annotated[str, Field(description="Category name to filter results")] = "",
        low_stock_threshold: Annotated[int, Field(description="Low stock threshold")] = 10,
    ) -> StockItemCollection:
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
        return StockItemCollection(
            items=TEST_STOCK
        )

    workflow = build_workflow(credential=azure_credential, mcp=[get_current_inventory_status], agent_suffix="-test")  # pyright: ignore[reportArgumentType]
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
    # Check that the items were in the original collection
    for item in workflow_outputs[0].data.items:
        assert item in TEST_STOCK
    assert workflow_outputs[0].data.summary


@pytest.mark.asyncio
async def test_no_restock_needed_path(azure_credential):
    """Demonstrate only having useless tools."""

    @ai_function
    def sing_a_song(lyrics: Annotated[str, Field(description="Lyrics to sing")]) -> str:
        """
        Sing a song with the given lyrics.
        """
        return f"Singing: {lyrics}"

    workflow = build_workflow(credential=azure_credential, mcp=[sing_a_song], agent_suffix="-test")  # pyright: ignore[reportArgumentType]


    test_message = ChatMessage(role="user", text="Help me restock store 1")
    result = await workflow.run(test_message)

    executor_completions = [event for event in result if isinstance(event, ExecutorCompletedEvent)]
    assert len(executor_completions) == 3  # Three executors should complete

    # Get the workflow output
    workflow_outputs = [event for event in result if isinstance(event, WorkflowOutputEvent)]
    assert len(workflow_outputs) == 1

    # There should not be any items to restock
    assert workflow_outputs[0].data is not None
    assert isinstance(workflow_outputs[0].data, RestockResult)
    assert len(workflow_outputs[0].data.items) == 0

