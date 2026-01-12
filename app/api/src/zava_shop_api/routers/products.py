
from fastapi import APIRouter, HTTPException, Query
import logging

from fastapi import HTTPException, Query
# Initialize in startup event
from fastapi_cache.decorator import cache


# SQLAlchemy imports for SQLite
from sqlalchemy import select, func

from zava_shop_shared.models.sqlite.products import Product as ProductModel
from zava_shop_shared.models.sqlite.categories import Category as CategoryModel
from zava_shop_shared.models.sqlite.product_types import ProductType as ProductTypeModel
from zava_shop_shared.models.sqlite.suppliers import Supplier as SupplierModel
from zava_shop_api.models import (Product, ProductList
)
from zava_shop_api.app import get_db_session


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/products", tags=["products"])


# Featured products endpoint
@router.get("/featured", response_model=ProductList)
@cache(expire=600)
async def get_featured_products(
    limit: int = Query(
        8, ge=1, le=50, description="Number of products to return")
) -> ProductList:
    """
    Get featured products for the homepage.
    Returns a curated selection of products with good ratings and availability.
    """
    try:
        async with get_db_session() as session:
            # Query for featured products
            # Strategy: Get products with good variety across categories
            # Prefer products with higher margins (more popular/profitable)
            # Exclude discontinued items
            stmt = (
                select(
                    ProductModel.product_id,
                    ProductModel.sku,
                    ProductModel.product_name,
                    CategoryModel.category_name,
                    ProductTypeModel.type_name,
                    ProductModel.base_price.label('unit_price'),
                    ProductModel.cost,
                    ProductModel.gross_margin_percent,
                    ProductModel.product_description,
                    SupplierModel.supplier_name,
                    ProductModel.discontinued,
                    ProductModel.image_url
                )
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
                .outerjoin(SupplierModel, ProductModel.supplier_id == SupplierModel.supplier_id)
                .where(ProductModel.discontinued == False)
                .order_by(ProductModel.gross_margin_percent.desc(), func.random())
                .limit(limit)
            )

            result = await session.execute(stmt)
            rows = result.all()

            products = []
            for row in rows:
                products.append(Product(
                    product_id=row.product_id,
                    sku=row.sku,
                    product_name=row.product_name,
                    category_name=row.category_name,
                    type_name=row.type_name,
                    unit_price=float(row.unit_price),
                    cost=float(row.cost),
                    gross_margin_percent=float(row.gross_margin_percent),
                    product_description=row.product_description,
                    supplier_name=row.supplier_name,
                    discontinued=row.discontinued,
                    image_url=row.image_url
                ))

            logger.info(f"Retrieved {len(products)} featured products")

            return ProductList(
                products=products,
                total=len(products)
            )

    except Exception as e:
        logger.error(f"Error fetching featured products: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch featured products: {str(e)}"
        )


# Get products by category endpoint
@router.get("/category/{category}", response_model=ProductList)
async def get_products_by_category(
    category: str,
    limit: int = Query(50, ge=1, le=100, description="Max products to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
) -> ProductList:
    """
    Get products filtered by category.
    Category names: Accessories, Apparel - Bottoms, Apparel - Tops, Footwear, Outerwear
    """
    try:
        async with get_db_session() as session:
            # Get total products in category for pagination
            total_stmt = (
                select(func.count())
                .select_from(ProductModel)
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .where(ProductModel.discontinued == False)
                .where(func.lower(CategoryModel.category_name) == func.lower(category))
            )
            total_result = await session.execute(total_stmt)
            total_count = total_result.scalar()

            if not total_count:
                raise HTTPException(
                    status_code=404,
                    detail=f"No products found in category '{category}'"
                )

            # Query products by category
            stmt = (
                select(
                    ProductModel.product_id,
                    ProductModel.sku,
                    ProductModel.product_name,
                    CategoryModel.category_name,
                    ProductTypeModel.type_name,
                    ProductModel.base_price.label('unit_price'),
                    ProductModel.cost,
                    ProductModel.gross_margin_percent,
                    ProductModel.product_description,
                    SupplierModel.supplier_name,
                    ProductModel.discontinued,
                    ProductModel.image_url
                )
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
                .outerjoin(SupplierModel, ProductModel.supplier_id == SupplierModel.supplier_id)
                .where(ProductModel.discontinued == False)
                .where(func.lower(CategoryModel.category_name) == func.lower(category))
                .order_by(ProductModel.product_name)
                .limit(limit)
                .offset(offset)
            )

            result = await session.execute(stmt)
            rows = result.all()

            products = []
            for row in rows:
                products.append(Product(
                    product_id=row.product_id,
                    sku=row.sku,
                    product_name=row.product_name,
                    category_name=row.category_name,
                    type_name=row.type_name,
                    unit_price=float(row.unit_price),
                    cost=float(row.cost),
                    gross_margin_percent=float(row.gross_margin_percent),
                    product_description=row.product_description,
                    supplier_name=row.supplier_name,
                    discontinued=row.discontinued,
                    image_url=row.image_url
                ))

            logger.info(
                f"Retrieved {len(products)} products for category '{category}'"
            )

            return ProductList(
                products=products,
                total=total_count
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching products by category: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch products: {str(e)}"
        )


# Get product by ID endpoint
@router.get("/{product_id}", response_model=Product)
async def get_product_by_id(product_id: int) -> Product:
    """
    Get a single product by its ID.
    Returns complete product information including category, type, and supplier.
    """
    try:
        async with get_db_session() as session:
            # Query single product by ID
            stmt = (
                select(
                    ProductModel.product_id,
                    ProductModel.sku,
                    ProductModel.product_name,
                    CategoryModel.category_name,
                    ProductTypeModel.type_name,
                    ProductModel.base_price.label('unit_price'),
                    ProductModel.cost,
                    ProductModel.gross_margin_percent,
                    ProductModel.product_description,
                    SupplierModel.supplier_name,
                    ProductModel.discontinued,
                    ProductModel.image_url
                )
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
                .outerjoin(SupplierModel, ProductModel.supplier_id == SupplierModel.supplier_id)
                .where(ProductModel.product_id == product_id)
            )

            result = await session.execute(stmt)
            row = result.first()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product with ID {product_id} not found"
                )

            product = Product(
                product_id=row.product_id,
                sku=row.sku,
                product_name=row.product_name,
                category_name=row.category_name,
                type_name=row.type_name,
                unit_price=float(row.unit_price),
                cost=float(row.cost),
                gross_margin_percent=float(row.gross_margin_percent),
                product_description=row.product_description,
                supplier_name=row.supplier_name,
                discontinued=row.discontinued,
                image_url=row.image_url
            )

            logger.info(
                f"Retrieved product {product_id}: {product.product_name}")

            return product

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching product {product_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch product: {str(e)}"
        )


@router.get("/sku/{sku}", response_model=Product)
async def get_product_by_sku(sku: str) -> Product:
    """
    Get a single product by its SKU.
    Returns complete product information including category, type, and supplier.
    """
    try:
        async with get_db_session() as session:
            # Query single product by SKU
            stmt = (
                select(
                    ProductModel.product_id,
                    ProductModel.sku,
                    ProductModel.product_name,
                    CategoryModel.category_name,
                    ProductTypeModel.type_name,
                    ProductModel.base_price.label('unit_price'),
                    ProductModel.cost,
                    ProductModel.gross_margin_percent,
                    ProductModel.product_description,
                    SupplierModel.supplier_name,
                    ProductModel.discontinued,
                    ProductModel.image_url
                )
                .join(CategoryModel, ProductModel.category_id == CategoryModel.category_id)
                .join(ProductTypeModel, ProductModel.type_id == ProductTypeModel.type_id)
                .outerjoin(SupplierModel, ProductModel.supplier_id == SupplierModel.supplier_id)
                .where(ProductModel.sku == sku)
            )

            result = await session.execute(stmt)
            row = result.first()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product with SKU '{sku}' not found"
                )

            product = Product(
                product_id=row.product_id,
                sku=row.sku,
                product_name=row.product_name,
                category_name=row.category_name,
                type_name=row.type_name,
                unit_price=float(row.unit_price),
                cost=float(row.cost),
                gross_margin_percent=float(row.gross_margin_percent),
                product_description=row.product_description,
                supplier_name=row.supplier_name,
                discontinued=row.discontinued,
                image_url=row.image_url
            )

            logger.info(
                f"Retrieved product by SKU {sku}: {product.product_name}")

            return product

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching product by SKU {sku}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch product: {str(e)}"
        )
