import os

from zava_shop_agents.insights import build_workflow, DataCollectionParameters

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
    workflow = build_workflow(credential=azure_credential, tools=[], agent_suffix="-test")  # pyright: ignore[reportArgumentType]
    params = DataCollectionParameters(store_id=1, user_role="store manager")
    result = await workflow.run(params)

    executor_completions = [event for event in result if getattr(event, "type", None) == "executor_completed"]
    assert len(executor_completions) >= 3  # Three+ executors should complete

