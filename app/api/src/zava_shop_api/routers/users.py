import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from zava_shop_shared.models.sqlite.customers import Customer as CustomerModel
from zava_shop_shared.models.sqlite.stores import Store as StoreModel

from zava_shop_api.customers import get_customer_orders
from zava_shop_api.models import CustomerProfile, OrderListResponse, TokenData
from zava_shop_api.openid_auth import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@router.get("/profile", response_model=CustomerProfile)
async def get_user_profile(request: Request, current_user: TokenData = Depends(get_current_user)) -> CustomerProfile:
    """
    Get profile information for the authenticated customer user.
    Requires authentication with customer role.
    Returns customer details including name, email, and primary store.
    """
    try:
        # Verify user has customer role and customer_id
        if current_user.user_role != "customer":
            raise HTTPException(status_code=403, detail="Only customers can access this endpoint")

        if not current_user.customer_id:
            raise HTTPException(status_code=403, detail="Customer ID not found in token")

        async with request.app.state.session_factory() as session:
            # Query customer profile
            stmt = (
                select(
                    CustomerModel.customer_id,
                    CustomerModel.first_name,
                    CustomerModel.last_name,
                    CustomerModel.email,
                    CustomerModel.phone,
                    CustomerModel.primary_store_id,
                    StoreModel.store_name,
                )
                .outerjoin(StoreModel, CustomerModel.primary_store_id == StoreModel.store_id)
                .where(CustomerModel.customer_id == current_user.customer_id)
            )

            result = await session.execute(stmt)
            row = result.first()

            if not row:
                raise HTTPException(status_code=404, detail="Customer profile not found")

            profile = CustomerProfile(
                customer_id=row.customer_id,
                first_name=row.first_name,
                last_name=row.last_name,
                email=row.email,
                phone=row.phone,
                primary_store_id=row.primary_store_id,
                primary_store_name=row.store_name,
            )

            logger.info(f"Retrieved profile for customer {current_user.username}")

            return profile

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile for user {current_user.username}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile: {str(e)}")


@router.get("/orders", response_model=OrderListResponse)
async def get_user_orders(request: Request, current_user: TokenData = Depends(get_current_user)) -> OrderListResponse:
    """
    Get all orders for the authenticated customer user.
    Requires authentication with customer role.
    Returns orders sorted by date (newest first) with all order items.
    """
    try:
        # Verify user has customer role and customer_id
        if current_user.user_role != "customer":
            raise HTTPException(status_code=403, detail="Only customers can access this endpoint")

        if not current_user.customer_id:
            raise HTTPException(status_code=403, detail="Customer ID not found in token")

        async with request.app.state.session_factory() as session:
            orders = await get_customer_orders(customer_id=current_user.customer_id, session=session)

        return orders

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching orders for user {current_user.username}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch orders: {str(e)}")
