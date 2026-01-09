from zava_shop_agents.supplier_review import build_workflow




@pytest.fixture
def azure_credential():
    # Replace with something else if needed
    return DefaultAzureCredential()


@pytest.mark.asyncio
async def test_simple_path(azure_credential):

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

