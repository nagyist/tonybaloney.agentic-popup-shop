from zava_shop_agents.supplier_review import build_workflow

import pytest
from azure.identity.aio import DefaultAzureCredential
from agent_framework import ChatMessage, ExecutorCompletedEvent


@pytest.fixture
def azure_credential():
    # Replace with something else if needed
    return DefaultAzureCredential()


@pytest.mark.asyncio
async def test_simple_path(azure_credential):

    with open("tests/data/test_proposal.md", "r", encoding="utf-8") as f:
        review_text = f.read()

    workflow = build_workflow(credential=azure_credential, tools=[], agent_suffix="-test")  # pyright: ignore[reportArgumentType]
    test_message = ChatMessage(role="user", text=review_text)
    result = await workflow.run(test_message)

    executor_completions = [event for event in result if isinstance(event, ExecutorCompletedEvent)]
    assert len(executor_completions) >= 3  # Three+ executors should complete

