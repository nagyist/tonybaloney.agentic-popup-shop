import json
import logging
from datetime import datetime, timezone
from typing import Optional

from agent_framework import (
    ChatMessage,
    ExecutorCompletedEvent,
    ExecutorFailedEvent,
    ExecutorInvokedEvent,
    WorkflowOutputEvent,
    WorkflowStartedEvent,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi_cache.decorator import cache
from pydantic import BaseModel
from sqlalchemy import case, func, select
from zava_shop_agents.admin_insights import build_workflow as admin_insights_workflow, AdminContext
from zava_shop_agents.insights import build_workflow as insights_workflow, DataCollectionParameters
from zava_shop_agents.insights_cache import get_cache
from zava_shop_agents.stock import build_workflow as stock_workflow
from zava_shop_shared.models.sqlite.categories import Category as CategoryModel
from zava_shop_shared.models.sqlite.inventory import Inventory as InventoryModel
from zava_shop_shared.models.sqlite.product_types import ProductType as ProductTypeModel
from zava_shop_shared.models.sqlite.products import Product as ProductModel
from zava_shop_shared.models.sqlite.stores import Store as StoreModel
from zava_shop_shared.models.sqlite.suppliers import Supplier as SupplierModel

from zava_shop_api.models import (
    CacheInfoResponse,
    CacheInvalidationResponse,
    Insight,
    InventoryItem,
    InventoryResponse,
    InventorySummary,
    ManagementProduct,
    ManagementProductResponse,
    ProductPagination,
    Supplier,
    SupplierList,
    TokenData,
    TopCategory,
    TopCategoryList,
    WeeklyInsights,
)

from ..openid_auth import (
    get_current_user,
    get_current_user_from_token,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/management", tags=["management"])


@router.get("/dashboard/top-categories", response_model=TopCategoryList)
@cache(expire=600)
async def get_top_categories(
    request: Request,
    limit: int = Query(5, ge=1, le=10, description="Number of top categories to return"),
    current_user: TokenData = Depends(get_current_user),
) -> TopCategoryList:
    """
    Get top categories by total inventory value (cost * stock).
    Returns categories ranked by revenue potential.
    Requires authentication. Store managers see only their store's data.
    """
    try:
        async with request.app.state.session_factory() as session:
            logger.info(f"Fetching top {limit} categories by inventory value for user {current_user.username}...")

            stmt = (
                select(
                    CategoryModel.category_name,
                    func.count(func.distinct(ProductModel.product_id)).label("product_count"),
                    func.sum(InventoryModel.stock_level).label("total_stock"),
                    func.sum(InventoryModel.stock_level * ProductModel.cost).label("total_cost_value"),
                    func.sum(InventoryModel.stock_level * ProductModel.base_price).label("total_retail_value"),
                    func.sum(InventoryModel.stock_level * (ProductModel.base_price - ProductModel.cost)).label(
                        "potential_profit"
                    ),
                )
                .select_from(InventoryModel)
                .join(ProductModel, InventoryModel.product_id == ProductModel.product_id)
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .where(ProductModel.discontinued == False)
            )

            # Apply store filter for store managers
            if current_user.store_id is not None:
                stmt = stmt.where(InventoryModel.store_id == current_user.store_id)

            stmt = (
                stmt.group_by(CategoryModel.category_name)
                .order_by(func.sum(InventoryModel.stock_level * ProductModel.base_price).desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            rows = result.all()

            if not rows:
                return TopCategoryList(categories=[], total=0, max_value=0.0)

            # Calculate max value for percentage calculation
            max_value = float(rows[0].total_retail_value) if rows else 0

            categories: list[TopCategory] = []
            for row in rows:
                retail_value = float(row.total_retail_value)
                percentage = round((retail_value / max_value * 100), 1) if max_value > 0 else 0

                categories.append(
                    TopCategory(
                        name=row.category_name,
                        revenue=round(retail_value, 2),
                        percentage=percentage,
                        product_count=int(row.product_count),
                        total_stock=int(row.total_stock),
                        cost_value=round(float(row.total_cost_value), 2),
                        potential_profit=round(float(row.potential_profit), 2),
                    )
                )

            logger.info(f"Retrieved {len(categories)} categories")

            return TopCategoryList(categories=categories, total=len(categories), max_value=round(max_value, 2))

    except Exception as e:
        logger.error(f"Error fetching top categories: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch top categories: {str(e)}")


@router.get("/insights", response_model=WeeklyInsights, response_model_exclude_none=False)
async def get_weekly_insights(
    store_id: Optional[int] = Query(
        None,
        ge=1,
        description="Store ID to generate insights for (admins only)",
    ),
    force_refresh: bool = Query(False, description="Force regenerate insights, bypassing cache"),
    current_user: TokenData = Depends(get_current_user),
) -> WeeklyInsights:
    """
    Get AI-generated weekly insights for the management dashboard.
    Returns cached insights if available and valid (< 7 days old).
    Set force_refresh=true to bypass cache and regenerate.
    Requires authentication.
    """
    try:
        logger.info(
            "Fetching weekly insights for user %s (role=%s, store=%s, force_refresh=%s)",
            current_user.username,
            current_user.user_role,
            current_user.store_id,
            force_refresh,
        )

        # Determine which store the workflow should focus on.
        if current_user.store_id is not None:
            # Store manager - use their assigned store
            target_store_id = current_user.store_id
            if store_id and store_id != current_user.store_id:
                logger.info(
                    "Store manager attempted to request store %s; enforcing assigned store %s.",
                    store_id,
                    current_user.store_id,
                )
        elif current_user.user_role == "admin":
            # Admin - use cache key 0 for enterprise-wide insights
            target_store_id = 0
        else:
            # Fallback for other roles
            target_store_id = store_id if store_id is not None else 0

        # Check cache first unless force refresh is requested
        cache = get_cache()
        if not force_refresh:
            cached_data = cache.get(target_store_id)
            if cached_data:
                logger.info(f"Returning cached insights for store {target_store_id}")
                return WeeklyInsights.model_validate(cached_data)

        # Cache miss or force refresh - generate new insights
        logger.info(f"Generating fresh insights for store {target_store_id}")

        # Select workflow based on user role
        if current_user.user_role == "admin":
            # Admin users get enterprise-wide insights
            logger.info("Using admin insights workflow for enterprise analysis")
            workflow = admin_insights_workflow()
            agent_input = AdminContext(
                user_role=current_user.user_role,
                days_back=30,
            )
        else:
            # Store managers get operational insights for their store
            logger.info(f"Using store manager insights workflow for store {target_store_id}")
            workflow = insights_workflow()
            agent_input = DataCollectionParameters(
                store_id=target_store_id,
                user_role=current_user.user_role,
            )

        insights_result: Optional[WeeklyInsights] = None
        fallback_payload: Optional[str] = None

        async for event in workflow.run_stream(agent_input):
            if isinstance(event, ExecutorFailedEvent):
                logger.error(
                    "Insights workflow failed in executor %s: %s",
                    event.executor_id,
                    event.details.message,
                )
                fallback_payload = event.details.message or "Insights workflow failed"
                break

            if isinstance(event, WorkflowOutputEvent):
                payload = event.data
                if isinstance(payload, BaseModel):
                    payload = payload.model_dump()

                if isinstance(payload, dict):
                    insights_result = WeeklyInsights.model_validate(payload)
                else:
                    fallback_payload = str(payload)
                break

        if insights_result:
            logger.info(
                "Generated dynamic weekly insights for user %s (store_id=%s)",
                current_user.username,
                target_store_id,
            )
            # Cache the successful result (include None values so frontend gets all fields)
            cache.set(target_store_id, insights_result.model_dump(exclude_none=False))
            return insights_result

        if fallback_payload:
            logger.warning(
                "Insights workflow returned non-structured payload: %s",
                fallback_payload,
            )
            return WeeklyInsights(
                store_id=target_store_id,
                summary="Dynamic insights are temporarily unavailable.",
                weather_summary="Weather data unavailable at this time.",
                events_summary=None,
                stock_items=[],
                insights=[
                    Insight(
                        type="warning",
                        title="Insights Service Unavailable",
                        description=fallback_payload,
                        action=None,
                    )
                ],
                unified_action=None,
            )

        raise HTTPException(
            status_code=502,
            detail="Insights workflow did not return data",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching weekly insights: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch weekly insights: {str(e)}")


@router.delete("/insights/cache", response_model=CacheInvalidationResponse)
async def invalidate_insights_cache(
    store_id: Optional[int] = Query(
        None, ge=1, description="Store ID to invalidate cache for. If not provided, invalidates all caches."
    ),
    current_user: TokenData = Depends(get_current_user),
) -> CacheInvalidationResponse:
    """
    Invalidate insights cache (admin only).
    If store_id is provided, invalidates cache for that store only.
    Otherwise, invalidates all cached insights.
    """
    # Check admin role
    if current_user.user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        cache = get_cache()

        if store_id:
            success = cache.invalidate(store_id)
            if success:
                return CacheInvalidationResponse(
                    success=True,
                    message=f"Cache invalidated for store {store_id}",
                    store_id=store_id,
                )
            else:
                return CacheInvalidationResponse(
                    success=False,
                    message=f"No cache found for store {store_id}",
                    store_id=store_id,
                )
        else:
            count = cache.invalidate_all()
            return CacheInvalidationResponse(
                success=True,
                message=f"Invalidated {count} cached insights",
                store_id=None,
            )
    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to invalidate cache: {str(e)}")


@router.get("/insights/cache/info", response_model=CacheInfoResponse)
async def get_insights_cache_info(
    store_id: int = Query(..., ge=1, description="Store ID to get cache info for"),
    current_user: TokenData = Depends(get_current_user),
) -> CacheInfoResponse:
    """
    Get cache metadata for a specific store (admin only).
    Returns cache status, age, and validity information.
    """
    # Check admin role
    if current_user.user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        cache = get_cache()
        info = cache.get_cache_info(store_id)

        if info:
            return CacheInfoResponse(
                success=True,
                cache_info=info,
                message=None,
            )
        else:
            return CacheInfoResponse(
                success=False,
                message=f"No cache found for store {store_id}",
                cache_info=None,
            )
    except Exception as e:
        logger.error(f"Error getting cache info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get cache info: {str(e)}")


@router.get("/suppliers", response_model=SupplierList)
async def get_suppliers(request: Request, current_user: TokenData = Depends(get_current_user)) -> SupplierList:
    """
    Get all suppliers with their details and associated product categories.
    Returns comprehensive supplier information for management interface.
    Requires authentication. Store managers see only suppliers for products in their store.
    """
    try:
        async with request.app.state.session_factory() as session:
            logger.info(f"Fetching suppliers for user {current_user.username}...")

            # Get basic supplier info
            stmt = select(
                SupplierModel.supplier_id,
                SupplierModel.supplier_name,
                SupplierModel.supplier_code,
                SupplierModel.contact_email,
                SupplierModel.contact_phone,
                SupplierModel.city,
                SupplierModel.state_province,
                SupplierModel.payment_terms,
                SupplierModel.lead_time_days,
                SupplierModel.minimum_order_amount,
                SupplierModel.bulk_discount_percent,
                SupplierModel.supplier_rating,
                SupplierModel.esg_compliant,
                SupplierModel.approved_vendor,
                SupplierModel.preferred_vendor,
                SupplierModel.active_status,
            ).where(SupplierModel.active_status == True)

            # If store manager, filter suppliers to only those with products in their store
            if current_user.store_id is not None:
                # Subquery to get supplier IDs for products in the manager's store
                supplier_subquery = (
                    select(func.distinct(ProductModel.supplier_id))
                    .select_from(InventoryModel)
                    .join(ProductModel, InventoryModel.product_id == ProductModel.product_id)
                    .where(InventoryModel.store_id == current_user.store_id)
                    .where(ProductModel.supplier_id.isnot(None))
                )
                stmt = stmt.where(SupplierModel.supplier_id.in_(supplier_subquery))

            stmt = stmt.order_by(
                SupplierModel.preferred_vendor.desc(), SupplierModel.supplier_rating.desc(), SupplierModel.supplier_name
            )

            result = await session.execute(stmt)
            rows = result.all()

            suppliers: list[Supplier] = []
            for row in rows:
                # Get categories for this supplier
                cat_stmt = (
                    select(func.distinct(CategoryModel.category_name))
                    .select_from(ProductModel)
                    .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                    .where(ProductModel.supplier_id == row.supplier_id)
                )
                cat_result = await session.execute(cat_stmt)
                categories = [cat_row[0] for cat_row in cat_result.all()]

                # Format location
                location = f"{row.city}, {row.state_province}" if row.city else "N/A"

                suppliers.append(
                    Supplier(
                        id=row.supplier_id,
                        name=row.supplier_name,
                        code=row.supplier_code,
                        location=location,
                        contact=row.contact_email,
                        phone=row.contact_phone or "N/A",
                        rating=float(row.supplier_rating) if row.supplier_rating else 0.0,
                        esg_compliant=row.esg_compliant,
                        approved=row.approved_vendor,
                        preferred=row.preferred_vendor,
                        categories=categories,
                        lead_time=row.lead_time_days,
                        payment_terms=row.payment_terms,
                        min_order=float(row.minimum_order_amount) if row.minimum_order_amount else 0.0,
                        bulk_discount=float(row.bulk_discount_percent) if row.bulk_discount_percent else 0.0,
                    )
                )

            logger.info(f"Retrieved {len(suppliers)} suppliers")

            return SupplierList(suppliers=suppliers, total=len(suppliers))

    except Exception as e:
        logger.error(f"Error fetching suppliers: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch suppliers: {str(e)}")


@router.get("/inventory", response_model=InventoryResponse)
async def get_inventory(
    request: Request,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    category: Optional[str] = None,
    low_stock_only: bool = False,
    low_stock_threshold: int = 10,
    limit: int = 100,
    current_user: TokenData = Depends(get_current_user),
) -> InventoryResponse:
    """
    Get inventory levels across stores with product and category details.
    Requires authentication. Store managers automatically see only their store's inventory.

    Args:
        store_id: Optional filter by specific store (admin only)
        product_id: Optional filter by specific product
        category: Optional filter by product category
        low_stock_only: Show only items with stock below reorder threshold
        low_stock_threshold: Threshold for considering stock as low (default: 10)
        limit: Maximum number of records to return
    """
    try:
        async with request.app.state.session_factory() as session:
            logger.info(
                f"Fetching inventory (store={store_id}, product={product_id}, category={category}, low_stock={low_stock_only})..."
            )

            # Build base query with joins
            base_stmt = (
                select(InventoryModel, StoreModel, ProductModel, CategoryModel, ProductTypeModel, SupplierModel)
                .select_from(InventoryModel)
                .join(StoreModel, InventoryModel.store_id == StoreModel.store_id)
                .join(ProductModel, InventoryModel.product_id == ProductModel.product_id)
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
                .outerjoin(SupplierModel, ProductModel.supplier_id == SupplierModel.supplier_id)
            )

            # Apply store filter - store managers can only see their store
            if current_user.store_id is not None:
                # Store manager - override any store_id parameter
                base_stmt = base_stmt.where(StoreModel.store_id == current_user.store_id)
            elif store_id is not None:
                # Admin with store filter
                base_stmt = base_stmt.where(StoreModel.store_id == store_id)

            if product_id is not None:
                base_stmt = base_stmt.where(ProductModel.product_id == product_id)

            if category:
                base_stmt = base_stmt.where(func.lower(CategoryModel.category_name) == func.lower(category))

            # Summary query - get statistics across ALL matching records
            summary_stmt = (
                select(
                    func.count(func.distinct(ProductModel.product_id)).label("total_items"),
                    func.sum(case((InventoryModel.stock_level < low_stock_threshold, 1), else_=0)).label(
                        "low_stock_count"
                    ),
                    func.sum(InventoryModel.stock_level * ProductModel.cost).label("total_stock_value"),
                    func.sum(InventoryModel.stock_level * ProductModel.base_price).label("total_retail_value"),
                    func.avg(InventoryModel.stock_level).label("avg_stock_level"),
                )
                .select_from(InventoryModel)
                .join(StoreModel, InventoryModel.store_id == StoreModel.store_id)
                .join(ProductModel, InventoryModel.product_id == ProductModel.product_id)
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
            )

            # Apply same filters to summary query
            if current_user.store_id is not None:
                # Store manager - override any store_id parameter
                summary_stmt = summary_stmt.where(StoreModel.store_id == current_user.store_id)
            elif store_id is not None:
                # Admin with store filter
                summary_stmt = summary_stmt.where(StoreModel.store_id == store_id)
            if product_id is not None:
                summary_stmt = summary_stmt.where(ProductModel.product_id == product_id)
            if category:
                summary_stmt = summary_stmt.where(func.lower(CategoryModel.category_name) == func.lower(category))

            # Execute summary query
            summary_result = await session.execute(summary_stmt)
            summary_row = summary_result.one()

            # Main query with ordering and limit
            main_stmt = base_stmt.order_by(
                InventoryModel.stock_level.asc(), StoreModel.store_name, ProductModel.product_name
            ).limit(limit)

            # Execute main query
            result = await session.execute(main_stmt)
            rows = result.all()

            inventory_items: list[InventoryItem] = []
            for row in rows:
                inventory = row[0]
                store = row[1]
                product = row[2]
                category_obj = row[3]
                product_type = row[4]
                supplier = row[5]

                stock_level = inventory.stock_level
                reorder_point = low_stock_threshold
                is_low_stock = stock_level < reorder_point

                # Skip if filtering for low stock only
                if low_stock_only and not is_low_stock:
                    continue

                # Calculate inventory value
                cost = float(product.cost) if product.cost else 0
                base_price = float(product.base_price) if product.base_price else 0
                stock_value = cost * stock_level
                retail_value = base_price * stock_level

                # Extract location from store name
                store_location = "Online Store"
                if store.is_online:
                    store_location = "Online Warehouse"
                else:
                    # Extract location from name (e.g., "Zava Pop-Up Bellevue Square" -> "Bellevue Square")
                    name_parts = store.store_name.split("Pop-Up ")
                    if len(name_parts) > 1:
                        store_location = name_parts[1]
                    else:
                        store_location = store.store_name

                inventory_items.append(
                    InventoryItem(
                        store_id=store.store_id,
                        store_name=store.store_name,
                        store_location=store_location,
                        is_online=store.is_online,
                        product_id=product.product_id,
                        product_name=product.product_name,
                        sku=product.sku,
                        category=category_obj.category_name,
                        type=product_type.type_name,
                        stock_level=stock_level,
                        reorder_point=reorder_point,
                        is_low_stock=is_low_stock,
                        unit_cost=cost,
                        unit_price=base_price,
                        stock_value=round(stock_value, 2),
                        retail_value=round(retail_value, 2),
                        supplier_name=supplier.supplier_name if supplier else None,
                        supplier_code=supplier.supplier_code if supplier else None,
                        lead_time=supplier.lead_time_days if supplier else None,
                        image_url=product.image_url,
                    )
                )

            # Use the summary statistics from the dedicated query
            total_items = int(summary_row.total_items) if summary_row.total_items else 0
            low_stock_count = int(summary_row.low_stock_count) if summary_row.low_stock_count else 0
            total_stock_value = float(summary_row.total_stock_value) if summary_row.total_stock_value else 0.0
            total_retail_value = float(summary_row.total_retail_value) if summary_row.total_retail_value else 0.0
            avg_stock = float(summary_row.avg_stock_level) if summary_row.avg_stock_level else 0.0

            logger.info(
                f"Retrieved {len(inventory_items)} inventory items (showing {len(inventory_items)} of {total_items} total, {low_stock_count} low stock)"
            )

            return InventoryResponse(
                inventory=inventory_items,
                summary=InventorySummary(
                    total_items=total_items,
                    low_stock_count=low_stock_count,
                    total_stock_value=round(total_stock_value, 2),
                    total_retail_value=round(total_retail_value, 2),
                    avg_stock_level=round(avg_stock, 1),
                ),
            )

    except Exception as e:
        logger.error(f"Error fetching inventory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch inventory: {str(e)}")


@router.get("/products", response_model=ManagementProductResponse)
async def get_products(
    request: Request,
    category: Optional[str] = None,
    supplier_id: Optional[int] = None,
    discontinued: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: TokenData = Depends(get_current_user),
) -> ManagementProductResponse:
    """
    Get products with detailed information including pricing, suppliers, and stock status.
    Requires authentication. Store managers see only products with inventory in their store.

    Args:
        category: Filter by category name
        supplier_id: Filter by supplier
        discontinued: Filter by discontinued status
        search: Search in product name, SKU, or description
        limit: Maximum number of records
        offset: Pagination offset
    """
    try:
        async with request.app.state.session_factory() as session:
            logger.info("Fetching products...")

            # Build base query
            stmt = (
                select(
                    ProductModel.product_id,
                    ProductModel.sku,
                    ProductModel.product_name,
                    ProductModel.product_description,
                    CategoryModel.category_name,
                    ProductTypeModel.type_name,
                    ProductModel.base_price,
                    ProductModel.cost,
                    ProductModel.gross_margin_percent,
                    ProductModel.discontinued,
                    SupplierModel.supplier_id,
                    SupplierModel.supplier_name,
                    SupplierModel.supplier_code,
                    SupplierModel.lead_time_days,
                    func.coalesce(func.sum(InventoryModel.stock_level), 0).label("total_stock"),
                    func.count(InventoryModel.store_id).label("store_count"),
                    ProductModel.image_url,
                )
                .select_from(ProductModel)
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
                .outerjoin(SupplierModel, ProductModel.supplier_id == SupplierModel.supplier_id)
                .outerjoin(InventoryModel, ProductModel.product_id == InventoryModel.product_id)
            )

            # Store manager filtering - only show products in their store
            if current_user.store_id is not None:
                stmt = stmt.where(InventoryModel.store_id == current_user.store_id)

            # Apply filters
            if category:
                stmt = stmt.where(func.lower(CategoryModel.category_name) == func.lower(category))

            if supplier_id is not None:
                stmt = stmt.where(ProductModel.supplier_id == supplier_id)

            if discontinued is not None:
                stmt = stmt.where(ProductModel.discontinued == discontinued)

            if search:
                search_pattern = f"%{search}%"
                stmt = stmt.where(
                    (func.lower(ProductModel.product_name).like(func.lower(search_pattern)))
                    | (func.lower(ProductModel.sku).like(func.lower(search_pattern)))
                    | (func.lower(ProductModel.product_description).like(func.lower(search_pattern)))
                )

            # Group by all non-aggregated columns
            stmt = stmt.group_by(
                ProductModel.product_id,
                CategoryModel.category_name,
                ProductTypeModel.type_name,
                SupplierModel.supplier_id,
                SupplierModel.supplier_name,
                SupplierModel.supplier_code,
                SupplierModel.lead_time_days,
                ProductModel.image_url,
            )

            # Get total count (need to count before limit/offset)
            count_stmt = select(func.count(func.distinct(ProductModel.product_id))).select_from(stmt.alias())
            total_result = await session.execute(count_stmt)
            total_count = total_result.scalar() or 0

            # Apply ordering and pagination
            stmt = stmt.order_by(ProductModel.product_name).limit(limit).offset(offset)

            result = await session.execute(stmt)
            rows = result.all()

            products = []
            for row in rows:
                base_price = float(row.base_price) if row.base_price else 0
                cost = float(row.cost) if row.cost else 0
                margin = float(row.gross_margin_percent) if row.gross_margin_percent else 0
                total_stock = int(row.total_stock)

                # Calculate inventory value
                stock_value = cost * total_stock
                retail_value = base_price * total_stock

                products.append(
                    ManagementProduct(
                        product_id=row.product_id,
                        sku=row.sku,
                        name=row.product_name,
                        description=row.product_description,
                        category=row.category_name,
                        type=row.type_name,
                        base_price=base_price,
                        cost=cost,
                        margin=margin,
                        discontinued=row.discontinued,
                        supplier_id=row.supplier_id,
                        supplier_name=row.supplier_name,
                        supplier_code=row.supplier_code,
                        lead_time=row.lead_time_days,
                        total_stock=total_stock,
                        store_count=int(row.store_count),
                        stock_value=round(stock_value, 2),
                        retail_value=round(retail_value, 2),
                        image_url=row.image_url,
                    )
                )

            logger.info(f"Retrieved {len(products)} products (total: {total_count})")

            return ManagementProductResponse(
                products=products,
                pagination=ProductPagination(
                    total=total_count, limit=limit, offset=offset, has_more=(offset + len(products)) < total_count
                ),
            )

    except Exception as e:
        logger.error(f"Error fetching products: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch products: {str(e)}")


@router.websocket("/ws/management/ai-agent/inventory")
async def websocket_ai_agent_inventory(websocket: WebSocket):
    """
    WebSocket endpoint for AI Inventory Agent.
    Streams workflow events back to the frontend in real-time.
    Requires authentication via token in the initial message.
    Store managers automatically use their assigned store_id.
    """
    await websocket.accept()
    current_user: Optional[TokenData] = None

    try:
        # Receive the initial request from the client
        data = await websocket.receive_text()
        request_data = json.loads(data)

        # Extract and validate authentication token
        token = request_data.get("token")
        if not token:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Authentication token required",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            await websocket.close(code=1008, reason="Authentication required")
            return

        current_user = await get_current_user_from_token(token)

        input_message = request_data.get("message", "Analyze inventory and recommend restocking priorities")

        # Store managers use their assigned store_id, admins can specify or use all stores
        if current_user.store_id is not None:
            # Store manager - use their store_id
            store_id = current_user.store_id
            logger.info(f"Store manager detected - using store_id: {store_id}")
        else:
            # Admin - can optionally specify store_id
            store_id = request_data.get("store_id")
            if store_id:
                logger.info(f"Admin specified store_id: {store_id}")
            else:
                logger.info("Admin analyzing all stores")

        logger.info(f"AI Agent request from {current_user.username}:   {input_message} (store_id: {store_id})")

        # Send initial acknowledgment
        await websocket.send_json(
            {
                "type": "started",
                "message": "AI Agent workflow initiated...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Run the workflow and stream events
        # Add store_id to the message if provided
        if store_id:
            full_message = f"{input_message}\n\nStore ID: {store_id}"
        else:
            full_message = input_message

        input: ChatMessage = ChatMessage(role="user", text=full_message)

        workflow_output = None
        workflow = stock_workflow()
        try:
            async for event in workflow.run_stream(input):
                now = datetime.now(timezone.utc).isoformat()
                if isinstance(event, WorkflowStartedEvent):
                    event_data = {"type": "workflow_started", "event": str(event.data), "timestamp": now}
                elif isinstance(event, WorkflowOutputEvent):
                    # Capture the workflow output (markdown result)
                    if isinstance(event.data, BaseModel):
                        workflow_output = event.data.model_dump()
                    else:
                        workflow_output = str(event.data)
                    event_data = {"type": "workflow_output", "event": workflow_output, "timestamp": now}
                elif isinstance(event, ExecutorInvokedEvent):
                    event_data = {
                        "type": "step_started",
                        "event": event.data,
                        "id": event.executor_id,
                        "timestamp": now,
                    }
                elif isinstance(event, ExecutorCompletedEvent):
                    event_data = {
                        "type": "step_completed",
                        "event": event.data,
                        "id": event.executor_id,
                        "timestamp": now,
                    }
                elif isinstance(event, ExecutorFailedEvent):
                    event_data = {
                        "type": "step_failed",
                        "event": event.details.message,
                        "id": event.executor_id,
                        "timestamp": now,
                    }
                else:
                    # Stream each workflow event to the frontend
                    event_data = {"type": "event", "event": str(event), "timestamp": now}
                await websocket.send_json(event_data)
                logger.info(f"📤 Sent event: {event}")

            # Send completion message with the workflow output
            await websocket.send_json(
                {
                    "type": "completed",
                    "message": "Workflow completed successfully",
                    "output": workflow_output,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.info("AI Agent workflow completed")

        except Exception as workflow_error:
            logger.error(f"Workflow error: {workflow_error}")
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Workflow error: {str(workflow_error)}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e), "timestamp": None})
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass
