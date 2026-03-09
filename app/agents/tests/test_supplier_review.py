import os

from zava_shop_agents.supplier_review import build_workflow

import pytest
from azure.identity.aio import DefaultAzureCredential

pytestmark = pytest.mark.skipif(
    not os.getenv("AZURE_AI_PROJECT_ENDPOINT"),
    reason="AZURE_AI_PROJECT_ENDPOINT is not configured for integration tests",
)


@pytest.fixture
def azure_credential():
    # Replace with something else if needed
    return DefaultAzureCredential()


@pytest.mark.asyncio
async def test_simple_path(azure_credential):

    with open("tests/data/test_proposal.md", "r", encoding="utf-8") as f:
        review_text = f.read()

    workflow = build_workflow(credential=azure_credential, tools=[], agent_suffix="-test")  # pyright: ignore[reportArgumentType]
    result = await workflow.run(review_text)

    executor_completions = [event for event in result if getattr(event, "type", None) == "executor_completed"]
    assert len(executor_completions) >= 3  # Three+ executors should complete

