# Copyright (c) Microsoft. All rights reserved.

import logging
import os
from typing import Any, List, Optional, Sequence, cast

from agent_framework import (
    Agent,
    Executor,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowEvent,
    handler,
)
from agent_framework_azure_ai import AzureAIClient
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from pydantic import Field

from zava_shop_agents import MCPStreamableHTTPToolOTEL, StrictModel

WORKFLOW_AGENT_DESCRIPTION = "Admin Weekly Insights Workflow Agent"
DEFAULT_MODEL = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5-mini")

logger = logging.getLogger(__name__)


class StorePerformanceEvent(WorkflowEvent):
    """Event emitted when store performance analysis is complete."""
    executor_id: Optional[str]

    def __init__(self, performance_data: "StorePerformanceAnalysis"):
        super().__init__(
            f"Store performance analysis complete - {len(performance_data.stores)} stores analyzed"
        )
        self.performance_data = performance_data


class AdminInsightsSynthesizedEvent(WorkflowEvent):
    """Event emitted when final admin insights are synthesized."""
    executor_id: Optional[str]

    def __init__(self, insights: "AdminWeeklyInsights"):
        super().__init__("Admin weekly insights generated successfully")
        self.insights = insights


DEFAULT_AZURE_API_VERSION = "2024-02-15-preview"


class AdminContext(StrictModel):
    """Admin user context for enterprise-wide insights.

    Contains user role verification for admin-level access.
    Unlike store manager workflows, no store_id filtering is needed
    since admins see all stores.
    """

    user_role: str
    days_back: int = Field(
        default=30, description="Number of days to analyze (default: 30)"
    )


class InsightAction(StrictModel):
    """Defines a clickable action button displayed on insight cards in the UI."""

    label: str = Field(..., description="Button label text")
    type: str = Field(..., description="Action type: 'navigation'")
    path: str = Field(..., description="Navigation path")
    instructions: Optional[str] = Field(
        default=None,
        description="Instructions to pre-fill in the AI agent interface",
    )


class Insight(StrictModel):
    """Represents a single insight card displayed in the admin dashboard."""

    type: str = Field(
        ..., description="Insight type: 'success', 'warning', or 'info'"
    )
    title: str = Field(..., description="Insight title/heading")
    description: str = Field(..., description="Detailed insight description")
    action: Optional[InsightAction] = Field(
        None, description="Optional action button"
    )


class StorePerformanceMetric(StrictModel):
    """Performance metrics for a single store."""

    store_id: int
    store_name: str
    is_online: bool
    total_revenue: float
    total_orders: int
    total_units_sold: int
    unique_customers: int
    avg_order_value: float
    revenue_per_customer: float
    efficiency_rank: int


class StorePerformanceAnalysis(StrictModel):
    """Output from StorePerformanceAnalyzer sent to InsightSynthesizer.

    Contains comprehensive performance data for all stores ranked by
    revenue-per-customer efficiency metric.
    """

    days_back: int
    stores: List[StorePerformanceMetric] = Field(
        ..., description="All stores ranked by efficiency"
    )
    top_performers: List[str] = Field(
        ...,
        description="Top 3 most efficient stores (formatted strings)",
    )
    bottom_performers: List[str] = Field(
        ...,
        description="Bottom 3 stores needing improvement (formatted strings)",
    )
    total_revenue: float = Field(
        ..., description="Total revenue across all stores"
    )
    total_customers: int = Field(
        ..., description="Total unique customers across all stores"
    )
    analysis_summary: str = Field(
        ..., description="AI-generated summary of performance patterns"
    )
    insight: Insight = Field(
        ..., description="UI-ready insight for store performance"
    )


class AdminWeeklyInsights(StrictModel):
    """Final workflow output returned to the admin dashboard UI.

    Provides enterprise-wide insights focused on comparative store
    performance, efficiency metrics, and strategic recommendations.

    Note: Inherits WeeklyInsights schema for API compatibility.
    Admin workflow doesn't use weather/events, so those fields are None.
    """

    store_id: int = Field(
        default=0, description="Store ID (0 for admin enterprise-wide insights)"
    )
    summary: str = Field(
        ..., description="AI-generated insights disclaimer (shown in italics)"
    )
    weather_summary: str = Field(
        default="N/A - Admin enterprise view",
        description="Not used in admin workflow"
    )
    events_summary: Optional[str] = Field(
        default=None,
        description="Not used in admin workflow"
    )
    stock_items: Optional[list[str]] = Field(
        default_factory=list,
        description="Not used in admin workflow"
    )
    insights: List[Insight] = Field(..., description="List of specific insights")
    unified_action: Optional[InsightAction] = Field(
        None,
        description="Single unified action for deep-dive analysis",
    )


class PerformanceToolResponse(StrictModel):
    stores: List[StorePerformanceMetric]


class AdminContextCollector(Executor):
    """Collects admin context and initiates performance analysis."""

    def __init__(self, id: str | None = None):
        super().__init__(id=id or "admin-context-collector")

    @handler
    async def handle(
        self, parameters: AdminContext, ctx: WorkflowContext[AdminContext]
    ) -> None:
        if not parameters.user_role or parameters.user_role.strip().lower() != "admin":
            raise ValueError(
                "User role is required for admin insights"
            )

        await ctx.send_message(parameters)


class StorePerformanceAnalyzer(Executor):
    """Analyzes store performance using Finance MCP get_store_performance_comparison tool."""

    agent: Agent

    def __init__(self, client: AzureAIClient, tools: Any | Sequence[Any], agent_suffix: str = ""):
        _id = "store-performance-analyzer" + agent_suffix
        # Create agent with Finance MCP tools - agent handles connection automatically
        self.agent = client.as_agent(
            name=_id,
            description=WORKFLOW_AGENT_DESCRIPTION,
            instructions=(
                "You are an enterprise retail analyst analyzing store performance across all locations. "
                "Your task: retrieve comprehensive performance metrics for all stores using the "
                "get_store_performance_comparison tool from Finance MCP. "
                "Pass days_back parameter to the tool. "
                "The tool returns stores ranked by revenue per customer (efficiency metric). "
                "Return the raw JSON data from the tool so it can be parsed and analyzed."
            ),
            tools=tools,
        )
        self.analysis_agent = client.as_agent(
            name="store-performance-analyzer-summarizer" + agent_suffix,
            description=WORKFLOW_AGENT_DESCRIPTION,
            instructions="Provide concise executive insights from store performance data."
        )
        super().__init__(id=_id)

    @handler
    async def handle(
        self,
        context: AdminContext,
        ctx: WorkflowContext[StorePerformanceAnalysis],
    ) -> None:
        """Fetch store performance comparison from Finance MCP via agent and analyze patterns."""
        try:
            # Use agent to call MCP tool - agent manages connection automatically
            prompt = (
                f"Get store performance comparison data for the last {context.days_back} days. "
                f"Use the get_store_performance_comparison tool with days_back={context.days_back}. "
                f"Return the complete results."
            )

            agent_response = await self.agent.run(
                prompt,
                response_format=PerformanceToolResponse
            )
            value = cast(PerformanceToolResponse, agent_response.value)

            # Extract stores from structured response
            stores = value.stores if value else []

            # If no results from agent, raise error
            if not stores:
                raise ValueError("No store performance data returned from Finance MCP tool")

            # Calculate totals
            total_revenue = sum(s.total_revenue for s in stores)
            total_customers = sum(s.unique_customers for s in stores)

            # Extract top and bottom performers
            top_3 = stores[:3] if len(stores) >= 3 else stores
            bottom_3 = stores[-3:] if len(stores) >= 3 else []

            # Format top performers
            top_performers = [
                f"#{store.efficiency_rank} {store.store_name}: ${store.revenue_per_customer:,.2f}/customer "
                f"({store.unique_customers} customers, ${store.total_revenue:,.2f} revenue)"
                for store in top_3
            ]

            # Format bottom performers
            bottom_performers = [
                f"#{store.efficiency_rank} {store.store_name}: ${store.revenue_per_customer:,.2f}/customer "
                f"({store.unique_customers} customers, ${store.total_revenue:,.2f} revenue)"
                for store in bottom_3
            ]

            # Generate analysis summary using separate LLM agent
            analysis_prompt = (
                f"Analyze this store performance data and provide executive insights:\n\n"
                f"Total Stores: {len(stores)}\n"
                f"Total Revenue: ${total_revenue:,.2f}\n"
                f"Total Customers: {total_customers:,}\n"
                f"Average Revenue per Customer: ${total_revenue/total_customers:,.2f}\n\n"
                f"Top 3 Performers (by revenue per customer):\n"
                f"{chr(10).join(top_performers)}\n\n"
                f"Bottom 3 Performers:\n"
                f"{chr(10).join(bottom_performers)}\n\n"
                f"Provide a concise 2-3 sentence analysis highlighting:\n"
                f"1) The efficiency gap between top and bottom performers\n"
                f"2) Key patterns or insights about what makes top stores successful\n"
                f"3) One actionable recommendation for improving bottom performers"
            )

            analysis_response = await self.analysis_agent.run(analysis_prompt)
            analysis_text = analysis_response.text or "Performance analysis completed."

            # Create detailed description for UI
            description_parts = [
                f"Analyzed {context.days_back}-day performance across {len(stores)} stores.",
                f"Total Revenue: ${total_revenue:,.2f} | Total Customers: {total_customers:,}",
                "",
                "Top Performers:",
            ]
            description_parts.extend(f"  {line}" for line in top_performers[:3])
            description_parts.extend(["", "Needs Improvement:"])
            description_parts.extend(f"  {line}" for line in bottom_performers[:3])

            # Create insight for UI
            performance_insight = Insight(
                type="info",
                title="Store Performance Comparison",
                description="\n".join(description_parts),
                action=InsightAction(
                    label="View Detailed Analysis",
                    type="navigation",
                    path="/management/ai-agent",
                    instructions=(
                        f"Analyze store performance trends and provide recommendations:\n\n"
                        f"{analysis_text}\n\n"
                        f"Review all {len(stores)} stores and identify opportunities for improvement."
                    ),
                ),
            )

            performance_data = StorePerformanceAnalysis(
                days_back=context.days_back,
                stores=stores,
                top_performers=top_performers,
                bottom_performers=bottom_performers,
                total_revenue=total_revenue,
                total_customers=total_customers,
                analysis_summary=analysis_text,
                insight=performance_insight,
            )

            performance_event = StorePerformanceEvent(performance_data)
            performance_event.executor_id = self.id
            await ctx.add_event(performance_event)
            await ctx.send_message(performance_data)

        except Exception as e:
            logger.error(
                "Store performance analysis failed: %s",
                str(e),
                exc_info=True,
            )
            # Create fallback insight for UI
            fallback_insight = Insight(
                type="warning",
                title="Store Performance Comparison",
                description="Unable to retrieve store performance data at this time. Check Finance MCP server availability.",
                action=None,
            )

            performance_data = StorePerformanceAnalysis(
                days_back=context.days_back,
                stores=[],
                top_performers=["Unable to retrieve performance data"],
                bottom_performers=[],
                total_revenue=0.0,
                total_customers=0,
                analysis_summary="Unable to retrieve store performance data at this time",
                insight=fallback_insight,
            )

            performance_event = StorePerformanceEvent(performance_data)
            performance_event.executor_id = self.id
            await ctx.add_event(performance_event)
            await ctx.send_message(performance_data)


class AdminInsightSynthesizer(Executor):
    """Synthesizes admin-level insights from store performance analysis."""

    def __init__(self, id: str | None = None):
        super().__init__(id=id or "admin-insight-synthesizer")

    @handler
    async def handle(
        self,
        performance_data: StorePerformanceAnalysis,
        ctx: WorkflowContext[AdminWeeklyInsights, AdminWeeklyInsights],
    ) -> None:
        """Generate final admin insights from performance analysis."""

        # Build unified action with comprehensive instructions
        unified_instructions = (
            f"Based on store performance analysis over the last {performance_data.days_back} days, "
            f"provide strategic recommendations for improving enterprise-wide performance.\n\n"
            f"## PERFORMANCE CONTEXT\n\n"
            f"{performance_data.analysis_summary}\n\n"
            f"### Top Performers\n"
            f"{chr(10).join(performance_data.top_performers)}\n\n"
            f"### Areas for Improvement\n"
            f"{chr(10).join(performance_data.bottom_performers)}\n\n"
        )

        unified_action = InsightAction(
            label="Generate Strategic Analysis",
            type="navigation",
            path="/management/ai-agent",
            instructions=unified_instructions,
        )

        insights = AdminWeeklyInsights(
            store_id=0,  # Cache key for admin enterprise-wide insights
            summary="AI-generated enterprise insights based on comparative store performance and efficiency metrics",
            weather_summary="N/A - Admin enterprise view",  # Required by WeeklyInsights schema
            events_summary=None,
            stock_items=[],
            insights=[performance_data.insight],
            unified_action=unified_action,
        )

        synth_event = AdminInsightsSynthesizedEvent(insights)
        synth_event.executor_id = self.id
        await ctx.add_event(synth_event)
        await ctx.send_message(insights)
        await ctx.yield_output(insights)


def build_workflow(
    credential: AsyncTokenCredential | None = None,
    project_endpoint: str | None = None,
    tools: Sequence[Any] | None = None,
    agent_suffix: str = "",
    user_token: str | None = None,
) -> Workflow:
    """Create and return the admin weekly insights workflow.

    Simpler than store manager workflow - no weather/events needed.
    Focuses on comparative store performance analysis using
    get_store_performance_comparison MCP tool.

    Returns:
        Workflow: Configured admin workflow ready for execution
    """

    if credential is None:
        credential = DefaultAzureCredential(
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
        )
    project_endpoint = project_endpoint or os.getenv("AZURE_AI_PROJECT_ENDPOINT")

    # Finance MCP Server tool
    if not tools:
        # Use user token if provided, otherwise fall back to DEV_GUEST_TOKEN for local dev
        auth_token = user_token or os.getenv('DEV_GUEST_TOKEN', 'dev-guest-token')
        tools = [MCPStreamableHTTPToolOTEL(
            name="FinanceMCP",
            url=os.getenv("FINANCE_MCP_HTTP", "http://localhost:8002") + "/mcp",
            headers={
                "Authorization": f"Bearer {auth_token}"
            },
            load_tools=True,
            load_prompts=False,
            request_timeout=30,
        )]


    context_collector = AdminContextCollector()
    performance_analyzer = StorePerformanceAnalyzer(
        AzureAIClient(credential=credential, project_endpoint=project_endpoint, model_deployment_name=DEFAULT_MODEL),
        agent_suffix=agent_suffix,
        tools=tools,
    )
    insight_synthesizer = AdminInsightSynthesizer()

    workflow = (
        WorkflowBuilder(
            start_executor=context_collector,
            name="Admin Weekly Insights Workflow",
            description=(
                "Generates enterprise-wide insights for admin users by analyzing "
                "comparative store performance metrics. Uses Finance MCP's "
                "get_store_performance_comparison tool to rank stores by efficiency "
                "(revenue per customer) and identify top performers and improvement opportunities."
            ),
        )
        .add_edge(context_collector, performance_analyzer)
        .add_edge(performance_analyzer, insight_synthesizer)
        .build()
    )

    return workflow
