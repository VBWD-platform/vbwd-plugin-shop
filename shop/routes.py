"""E-commerce routes — public catalog + admin management."""
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, current_app, jsonify, request, g
from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_admin, require_permission

from plugins.shop.shop.repositories.product_repository import ProductRepository
from plugins.shop.shop.repositories.product_category_repository import (
    ProductCategoryRepository,
)
from plugins.shop.shop.repositories.warehouse_stock_repository import (
    WarehouseStockRepository,
)
from plugins.shop.shop.repositories.warehouse_repository import WarehouseRepository
from plugins.shop.shop.repositories.order_repository import OrderRepository
from plugins.shop.shop.services.product_pricing_service import ProductPricingService
from plugins.shop.shop.models.product import validate_price_display_mode
from vbwd.models.tax import Tax

shop_bp = Blueprint("shop", __name__)

# The cents quantize boundary for splitting a gross coupon discount into its
# netto / tax portions on the invoice (the only rounding done in the route;
# per-line tax rounding stays in ``vbwd/pricing/line_tax_fields``).
#
# NOTE (S96.6): these two helpers are intentionally a small DUPLICATE of the
# booking plugin's ``_split_discount_tax_breakdown`` / discount roll-up — shop
# must NOT import from booking (no undeclared plugin→plugin dependency), and the
# code is too small / vertical-specific to justify a new core seam. Shop differs
# from booking in that it has MULTIPLE product lines, so the per-rate split is
# computed against the AGGREGATED pre-discount per-rate tax across all lines.
_CENTS = Decimal("0.01")


def _aggregate_pre_discount_tax_breakdown(product_lines):
    """Sum the product lines' ``tax_breakdown`` by (code, rate).

    Returns an ordered list of ``{code, name, rate, amount}`` with POSITIVE
    aggregated amounts — the pre-discount per-rate tax the discount is split
    against. Order follows first appearance so the result is deterministic.
    """
    aggregated = {}
    order = []
    for line in product_lines:
        for entry in line.tax_breakdown or []:
            key = (entry["code"], str(entry["rate"]))
            if key not in aggregated:
                aggregated[key] = {
                    "code": entry["code"],
                    "name": entry["name"],
                    "rate": entry["rate"],
                    "amount": Decimal("0.00"),
                }
                order.append(key)
            aggregated[key]["amount"] += Decimal(str(entry["amount"]))
    return [aggregated[key] for key in order]


def _split_discount_tax_breakdown(aggregated_breakdown, tax_discount):
    """Split a negative tax discount per rate, proportional to pre-discount tax.

    ``aggregated_breakdown`` is the order's per-rate tax (positive amounts),
    aggregated across all product lines. ``tax_discount`` is the (positive) total
    tax portion of the gross discount. Returns a per-rate breakdown of NEGATIVE
    amounts that sums EXACTLY to ``-tax_discount`` (to the cent) — any rounding
    residual is absorbed into the largest-magnitude component so the aggregated
    per-rate display reconciles with the invoice tax.
    """
    positive_amounts = [Decimal(str(entry["amount"])) for entry in aggregated_breakdown]
    pre_tax_total = sum(positive_amounts, Decimal("0.00"))
    if pre_tax_total <= Decimal("0"):
        return []

    discount_amounts = [
        (tax_discount * amount / pre_tax_total).quantize(_CENTS, rounding=ROUND_HALF_UP)
        for amount in positive_amounts
    ]
    # Absorb the rounding residual into the largest-magnitude component so the
    # split sums to exactly ``tax_discount`` (one rounding boundary).
    residual = tax_discount - sum(discount_amounts, Decimal("0.00"))
    if residual != Decimal("0.00"):
        largest_index = max(
            range(len(discount_amounts)),
            key=lambda index: abs(discount_amounts[index]),
        )
        discount_amounts[largest_index] += residual

    return [
        {
            "code": entry["code"],
            "name": entry["name"],
            "rate": entry["rate"],
            "amount": float(-amount),
        }
        for entry, amount in zip(aggregated_breakdown, discount_amounts)
    ]


class TaxAssignmentError(ValueError):
    """Raised when a requested ``tax_ids`` entry is unknown or inactive."""


def _resolve_active_taxes(tax_ids):
    """Resolve ``tax_ids`` to active core taxes, deduped and order-preserving.

    Raises ``TaxAssignmentError`` if any id is unknown or its tax is inactive.
    """
    deduped = list(dict.fromkeys(tax_ids))
    if not deduped:
        return []

    found = {
        str(tax.id): tax
        for tax in db.session.query(Tax).filter(Tax.id.in_(deduped)).all()
    }
    resolved = []
    for tax_id in deduped:
        tax = found.get(str(tax_id))
        if tax is None:
            raise TaxAssignmentError(f"Unknown tax: {tax_id}")
        if not tax.is_active:
            raise TaxAssignmentError(f"Tax is not active: {tax_id}")
        resolved.append(tax)
    return resolved


# ── Public: Catalog ──────────────────────────────────────────────────────


@shop_bp.route("/api/v1/shop/products", methods=["GET"])
def list_products():
    """Product catalog with search, category filter, pagination."""
    repo = ProductRepository(db.session)
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    if search:
        products = repo.search(search, page, per_page)
    elif category:
        products = repo.find_by_category_slug(category, page, per_page)
    else:
        products = repo.find_active(page, per_page)

    pricing_service = ProductPricingService(current_app.container.price_factory())
    product_dicts = []
    for product in products:
        product_dict = product.to_dict()
        product_dict["pricing"] = pricing_service.get_product_pricing_payload(product)
        product_dicts.append(product_dict)

    return (
        jsonify(
            {
                "products": product_dicts,
                "page": page,
                "per_page": per_page,
                "total": repo.count_active(),
            }
        ),
        200,
    )


@shop_bp.route("/api/v1/shop/products/<slug>", methods=["GET"])
def get_product(slug):
    """Product detail with images, variants, stock status."""
    repo = ProductRepository(db.session)
    product = repo.find_by_slug(slug)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    stock_repo = WarehouseStockRepository(db.session)
    product_dict = product.to_dict()
    product_dict["pricing"] = ProductPricingService(
        current_app.container.price_factory()
    ).get_product_pricing_payload(product)

    if product.has_variants:
        for variant in product_dict.get("variants", []):
            from uuid import UUID

            available = stock_repo.get_total_available(product.id, UUID(variant["id"]))
            variant["stock_available"] = available
    else:
        product_dict["stock_available"] = stock_repo.get_total_available(product.id)

    # S77 — append the generic tags / custom fields (opt-in, no model import).
    # The display components on the card read these keys + field defs (labels +
    # types) without an extra round trip.
    from vbwd.services.tags_and_custom_fields import (
        append_tags_and_custom_fields,
        resolve_tags_and_custom_fields,
    )

    append_tags_and_custom_fields(product_dict, "shop_product", product.id)
    product_dict["custom_field_defs"] = resolve_tags_and_custom_fields().get_field_defs(
        "shop_product"
    )

    return jsonify({"product": product_dict}), 200


@shop_bp.route("/api/v1/shop/categories", methods=["GET"])
def list_categories():
    """Category tree."""
    repo = ProductCategoryRepository(db.session)
    categories = repo.find_root_categories()
    return (
        jsonify(
            {
                "categories": [c.to_dict() for c in categories],
            }
        ),
        200,
    )


@shop_bp.route("/api/v1/shop/categories/<slug>", methods=["GET"])
def get_category(slug):
    """Category detail with products."""
    repo = ProductCategoryRepository(db.session)
    category = repo.find_by_slug(slug)
    if not category:
        return jsonify({"error": "Category not found"}), 404
    return jsonify({"category": category.to_dict()}), 200


# ── Public: Orders ───────────────────────────────────────────────────────


@shop_bp.route("/api/v1/shop/orders", methods=["GET"])
@require_auth
def list_user_orders():
    """User's order history."""
    repo = OrderRepository(db.session)
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    orders = repo.find_by_user(g.user_id, page, per_page)
    return (
        jsonify(
            {
                "orders": [o.to_dict() for o in orders],
                "total": repo.count_by_user(g.user_id),
            }
        ),
        200,
    )


@shop_bp.route("/api/v1/shop/orders/<order_id>", methods=["GET"])
@require_auth
def get_user_order(order_id):
    """Order detail."""
    repo = OrderRepository(db.session)
    order = repo.find_by_id(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    if str(order.user_id) != str(g.user_id):
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({"order": order.to_dict()}), 200


# ── Admin: Products ──────────────────────────────────────────────────────


@shop_bp.route("/api/v1/admin/shop/products", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.products.view")
def admin_list_products():
    """Admin product list (all, including inactive)."""
    repo = ProductRepository(db.session)
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 25))
    products = repo.find_all(limit=per_page, offset=(page - 1) * per_page)
    return (
        jsonify(
            {
                "products": [p.to_dict() for p in products],
                "page": page,
                "per_page": per_page,
            }
        ),
        200,
    )


@shop_bp.route("/api/v1/admin/shop/products", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_create_product():
    """Create a new product."""
    from uuid import uuid4
    from plugins.shop.shop.models.product import Product

    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"error": "Name is required"}), 400

    slug = data.get("slug") or data["name"].lower().replace(" ", "-")
    repo = ProductRepository(db.session)

    if repo.find_by_slug(slug):
        return jsonify({"error": f"Product with slug '{slug}' already exists"}), 400

    try:
        price_display_mode = validate_price_display_mode(data.get("price_display_mode"))
    except ValueError as mode_error:
        return jsonify({"error": str(mode_error)}), 400

    product = Product(
        id=uuid4(),
        name=data["name"],
        slug=slug,
        description=data.get("description"),
        sku=data.get("sku"),
        price=float(data.get("price", 0)),
        is_active=data.get("is_active", True),
        is_digital=data.get("is_digital", False),
        has_variants=data.get("has_variants", False),
        weight=data.get("weight"),
        dimensions=data.get("dimensions", {}),
        tax_class=data.get("tax_class", "standard"),
        price_display_mode=price_display_mode,
    )

    if "tax_ids" in data:
        try:
            product.taxes = _resolve_active_taxes(data["tax_ids"])
        except TaxAssignmentError as tax_error:
            return jsonify({"error": str(tax_error)}), 400

    repo.save(product)

    return jsonify({"product": product.to_dict(), "message": "Product created"}), 201


@shop_bp.route("/api/v1/admin/shop/products/<product_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.products.view")
def admin_get_product(product_id):
    """Admin product detail."""
    repo = ProductRepository(db.session)
    product = repo.find_by_id(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify({"product": product.to_dict()}), 200


@shop_bp.route("/api/v1/admin/shop/products/<product_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_update_product(product_id):
    """Update product."""
    repo = ProductRepository(db.session)
    product = repo.find_by_id(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    data = request.get_json() or {}
    for field_name in [
        "name",
        "description",
        "sku",
        "is_active",
        "is_digital",
        "has_variants",
        "weight",
        "dimensions",
        "tax_class",
    ]:
        if field_name in data:
            setattr(product, field_name, data[field_name])
    if "price" in data:
        product.price = float(data["price"])
    if "price_display_mode" in data:
        try:
            product.price_display_mode = validate_price_display_mode(
                data["price_display_mode"]
            )
        except ValueError as mode_error:
            return jsonify({"error": str(mode_error)}), 400
    if "tax_ids" in data:
        # Replace-set: the new assignment fully supersedes the old one.
        try:
            product.taxes = _resolve_active_taxes(data["tax_ids"])
        except TaxAssignmentError as tax_error:
            return jsonify({"error": str(tax_error)}), 400

    repo.save(product)
    return jsonify({"product": product.to_dict()}), 200


@shop_bp.route("/api/v1/admin/shop/products/<product_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_delete_product(product_id):
    """Delete product."""
    repo = ProductRepository(db.session)
    product = repo.find_by_id(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    repo.delete(product)
    return jsonify({"message": "Product deleted"}), 200


# ── Admin: Orders ────────────────────────────────────────────────────────


@shop_bp.route("/api/v1/admin/shop/orders", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.orders.view")
def admin_list_orders():
    """Admin order list with optional status filter."""
    from plugins.shop.shop.models.order import OrderStatus

    repo = OrderRepository(db.session)
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 25))
    status_filter = request.args.get("status", "").strip()

    if status_filter:
        try:
            status = OrderStatus(status_filter)
            orders = repo.find_by_status(status, page, per_page)
        except ValueError:
            return jsonify({"error": f"Invalid status: {status_filter}"}), 400
    else:
        orders = repo.find_all(limit=per_page, offset=(page - 1) * per_page)

    return (
        jsonify(
            {
                "orders": [o.to_dict() for o in orders],
                "page": page,
                "per_page": per_page,
            }
        ),
        200,
    )


@shop_bp.route("/api/v1/admin/shop/orders/<order_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.orders.view")
def admin_get_order(order_id):
    """Admin order detail."""
    repo = OrderRepository(db.session)
    order = repo.find_by_id(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({"order": order.to_dict()}), 200


@shop_bp.route("/api/v1/admin/shop/orders/<order_id>/ship", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.orders.manage")
def admin_ship_order(order_id):
    """Mark order as shipped with tracking info."""
    from plugins.shop.shop.models.order import OrderStatus

    repo = OrderRepository(db.session)
    order = repo.find_by_id(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    data = request.get_json() or {}
    order.status = OrderStatus.SHIPPED
    order.tracking_number = data.get("tracking_number")
    order.tracking_url = data.get("tracking_url")
    repo.save(order)

    return jsonify({"order": order.to_dict(), "message": "Order shipped"}), 200


@shop_bp.route("/api/v1/admin/shop/orders/<order_id>/complete", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.orders.manage")
def admin_complete_order(order_id):
    """Mark order as completed."""
    from plugins.shop.shop.models.order import OrderStatus

    repo = OrderRepository(db.session)
    order = repo.find_by_id(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    order.status = OrderStatus.COMPLETED
    repo.save(order)

    return jsonify({"order": order.to_dict(), "message": "Order completed"}), 200


# ── Admin: Warehouses + Stock ────────────────────────────────────────────


@shop_bp.route("/api/v1/admin/shop/warehouses", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.warehouses.manage")
def admin_list_warehouses():
    """List warehouses."""
    repo = WarehouseRepository(db.session)
    warehouses = repo.find_active()
    return jsonify({"warehouses": [w.to_dict() for w in warehouses]}), 200


@shop_bp.route("/api/v1/admin/shop/warehouses/<warehouse_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.warehouses.manage")
def admin_get_warehouse(warehouse_id):
    """Warehouse detail with stock levels."""
    repo = WarehouseRepository(db.session)
    warehouse = repo.find_by_id(warehouse_id)
    if not warehouse:
        return jsonify({"error": "Warehouse not found"}), 404

    stock_repo = WarehouseStockRepository(db.session)
    stock_items = stock_repo.find_all()

    # Enrich stock with product names
    product_repo = ProductRepository(db.session)
    enriched_stock = []
    for stock_item in stock_items:
        if str(stock_item.warehouse_id) != str(warehouse_id):
            continue
        item_dict = stock_item.to_dict()
        product = product_repo.find_by_id(stock_item.product_id)
        item_dict["product_name"] = product.name if product else "Unknown"
        item_dict["product_sku"] = product.sku if product else ""
        enriched_stock.append(item_dict)

    result = warehouse.to_dict()
    result["stock"] = enriched_stock
    return jsonify({"warehouse": result}), 200


@shop_bp.route("/api/v1/admin/shop/warehouses/<warehouse_id>/stock", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.warehouses.manage")
def admin_warehouse_stock(warehouse_id):
    """Warehouse stock detail — same as warehouse detail but stock-only."""
    stock_repo = WarehouseStockRepository(db.session)
    product_repo = ProductRepository(db.session)
    stock_items = stock_repo.find_all()

    enriched = []
    for stock_item in stock_items:
        if str(stock_item.warehouse_id) != str(warehouse_id):
            continue
        item_dict = stock_item.to_dict()
        product = product_repo.find_by_id(stock_item.product_id)
        item_dict["product_name"] = product.name if product else "Unknown"
        item_dict["product_sku"] = product.sku if product else ""
        enriched.append(item_dict)

    return jsonify({"stock": enriched}), 200


# ── Admin: Categories ────────────────────────────────────────────────


@shop_bp.route("/api/v1/admin/shop/categories", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.categories.manage")
def admin_list_categories():
    """Admin category list."""
    repo = ProductCategoryRepository(db.session)
    fmt = request.args.get("format", "flat")
    if fmt == "tree":
        categories = repo.find_root_categories()
    else:
        categories = repo.find_all_sorted()
    return jsonify({"categories": [c.to_dict() for c in categories]}), 200


@shop_bp.route("/api/v1/admin/shop/categories", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.categories.manage")
def admin_create_category():
    """Create product category."""
    from uuid import uuid4
    from plugins.shop.shop.models.product_category import ProductCategory

    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"error": "Name is required"}), 400

    slug = data.get("slug") or data["name"].lower().replace(" ", "-")
    repo = ProductCategoryRepository(db.session)
    if repo.find_by_slug(slug):
        return jsonify({"error": f"Category '{slug}' already exists"}), 400

    category = ProductCategory(
        id=uuid4(),
        name=data["name"],
        slug=slug,
        description=data.get("description"),
        image_url=data.get("image_url"),
        parent_id=data.get("parent_id"),
        sort_order=int(data.get("sort_order", 0)),
    )
    repo.save(category)
    return jsonify({"category": category.to_dict()}), 201


@shop_bp.route("/api/v1/admin/shop/categories/<category_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.categories.manage")
def admin_get_category(category_id):
    """Category detail."""
    repo = ProductCategoryRepository(db.session)
    category = repo.find_by_id(category_id)
    if not category:
        return jsonify({"error": "Category not found"}), 404
    return jsonify({"category": category.to_dict()}), 200


@shop_bp.route("/api/v1/admin/shop/categories/<category_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("shop.categories.manage")
def admin_update_category(category_id):
    """Update category."""
    repo = ProductCategoryRepository(db.session)
    category = repo.find_by_id(category_id)
    if not category:
        return jsonify({"error": "Category not found"}), 404

    data = request.get_json() or {}
    for field_name in [
        "name",
        "slug",
        "description",
        "image_url",
        "parent_id",
        "sort_order",
    ]:
        if field_name in data:
            setattr(category, field_name, data[field_name])
    repo.save(category)
    return jsonify({"category": category.to_dict()}), 200


@shop_bp.route("/api/v1/admin/shop/categories/<category_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("shop.categories.manage")
def admin_delete_category(category_id):
    """Delete category."""
    repo = ProductCategoryRepository(db.session)
    category = repo.find_by_id(category_id)
    if not category:
        return jsonify({"error": "Category not found"}), 404
    repo.delete(category)
    return jsonify({"message": "Category deleted"}), 200


# ── Admin: Stock ─────────────────────────────────────────────────────


@shop_bp.route("/api/v1/admin/shop/stock", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.stock.manage")
def admin_stock_overview():
    """Cross-warehouse stock overview with product names."""
    stock_repo = WarehouseStockRepository(db.session)
    product_repo = ProductRepository(db.session)
    warehouse_repo = WarehouseRepository(db.session)
    stock_items = stock_repo.find_all()

    enriched = []
    for stock_item in stock_items:
        item_dict = stock_item.to_dict()
        product = product_repo.find_by_id(stock_item.product_id)
        warehouse = warehouse_repo.find_by_id(stock_item.warehouse_id)
        item_dict["product_name"] = product.name if product else "Unknown"
        item_dict["product_slug"] = product.slug if product else ""
        item_dict["product_sku"] = product.sku if product else ""
        item_dict["warehouse_name"] = warehouse.name if warehouse else "Unknown"
        enriched.append(item_dict)

    return jsonify({"stock": enriched}), 200


@shop_bp.route("/api/v1/admin/shop/stock/<product_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("shop.stock.manage")
def admin_update_stock(product_id):
    """Update stock for a product in a warehouse."""
    data = request.get_json() or {}
    warehouse_id = data.get("warehouse_id")
    if not warehouse_id:
        return jsonify({"error": "warehouse_id is required"}), 400

    stock_repo = WarehouseStockRepository(db.session)
    stock = stock_repo.find_by_product_and_warehouse(product_id, warehouse_id)
    if not stock:
        from uuid import uuid4
        from plugins.shop.shop.models.warehouse_stock import WarehouseStock as WS

        stock = WS(
            id=uuid4(),
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=int(data.get("quantity", 0)),
            low_stock_threshold=int(data.get("low_stock_threshold", 10)),
        )
        db.session.add(stock)
        db.session.commit()
    else:
        if "quantity" in data:
            stock.quantity = int(data["quantity"])
        if "low_stock_threshold" in data:
            stock.low_stock_threshold = int(data["low_stock_threshold"])
        stock_repo.save(stock)

    return jsonify({"stock": stock.to_dict()}), 200


# ── Admin: Product Images ────────────────────────────────────────────


def _cms_available():
    """Check if CMS plugin is installed."""
    from importlib.util import find_spec

    return find_spec("plugins.cms.src.services.cms_image_service") is not None


@shop_bp.route("/api/v1/admin/shop/products/<product_id>/images", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.products.view")
def admin_list_product_images(product_id):
    """List product images."""
    from plugins.shop.shop.models.product_image import ProductImage

    images = (
        db.session.query(ProductImage)
        .filter_by(product_id=product_id)
        .order_by(ProductImage.sort_order)
        .all()
    )
    return jsonify({"images": [img.to_dict() for img in images]}), 200


@shop_bp.route("/api/v1/admin/shop/products/<product_id>/images", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_upload_product_image(product_id):
    """Upload a product image via CMS file storage."""
    if not _cms_available():
        return jsonify({"error": "CMS plugin required for image uploads"}), 501

    if "file" not in request.files:
        return jsonify({"error": "file upload required"}), 400

    uploaded_file = request.files["file"]
    file_data = uploaded_file.read()
    filename = uploaded_file.filename or "image.jpg"
    mime_type = uploaded_file.content_type or "image/jpeg"

    from plugins.cms.src.services.cms_image_service import CmsImageService
    from plugins.cms.src.repositories.cms_image_repository import CmsImageRepository
    from vbwd.interfaces.file_storage import ManagerBackedFileStorage
    from plugins.shop.shop.models.product_image import ProductImage

    image_repo = CmsImageRepository(db.session)
    storage = ManagerBackedFileStorage(current_app.container.filesystem_manager())
    cms_service = CmsImageService(image_repo, storage)

    cms_image_data = cms_service.upload_image(file_data, filename, mime_type)

    existing_count = (
        db.session.query(ProductImage).filter_by(product_id=product_id).count()
    )

    product_image = ProductImage(
        product_id=product_id,
        url=cms_image_data.get("url_path") or cms_image_data.get("url", ""),
        alt=cms_image_data.get("alt_text", ""),
        sort_order=existing_count,
        is_primary=existing_count == 0,
    )
    db.session.add(product_image)
    db.session.commit()
    return jsonify({"image": product_image.to_dict()}), 201


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/images/<image_id>/primary",
    methods=["POST"],
)
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_set_product_image_primary(product_id, image_id):
    """Set a product image as primary."""
    from plugins.shop.shop.models.product_image import ProductImage

    db.session.query(ProductImage).filter_by(product_id=product_id).update(
        {"is_primary": False}
    )

    target = (
        db.session.query(ProductImage)
        .filter_by(id=image_id, product_id=product_id)
        .first()
    )
    if not target:
        return jsonify({"error": "Image not found"}), 404

    target.is_primary = True
    db.session.commit()
    return jsonify({"image": target.to_dict()}), 200


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/images/<image_id>",
    methods=["DELETE"],
)
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_delete_product_image(product_id, image_id):
    """Delete a product image."""
    from plugins.shop.shop.models.product_image import ProductImage

    target = (
        db.session.query(ProductImage)
        .filter_by(id=image_id, product_id=product_id)
        .first()
    )
    if not target:
        return jsonify({"error": "Image not found"}), 404

    was_primary = target.is_primary
    db.session.delete(target)
    db.session.flush()

    if was_primary:
        next_image = (
            db.session.query(ProductImage)
            .filter_by(product_id=product_id)
            .order_by(ProductImage.sort_order)
            .first()
        )
        if next_image:
            next_image.is_primary = True

    db.session.commit()
    return jsonify({"message": "Image deleted"}), 200


# ── Admin: Bulk Product Operations ───────────────────────────────────


@shop_bp.route("/api/v1/admin/shop/products/bulk-delete", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_bulk_delete_products():
    """Bulk delete products."""
    data = request.get_json() or {}
    product_ids = data.get("product_ids", [])
    if not product_ids:
        return jsonify({"error": "product_ids required"}), 400

    repo = ProductRepository(db.session)
    deleted = 0
    for pid in product_ids:
        product = repo.find_by_id(pid)
        if product:
            repo.delete(product)
            deleted += 1
    return jsonify({"deleted": deleted}), 200


@shop_bp.route("/api/v1/admin/shop/products/bulk-activate", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_bulk_activate_products():
    """Bulk activate products."""
    data = request.get_json() or {}
    product_ids = data.get("product_ids", [])
    repo = ProductRepository(db.session)
    updated = 0
    for pid in product_ids:
        product = repo.find_by_id(pid)
        if product:
            product.is_active = True
            repo.save(product)
            updated += 1
    return jsonify({"updated": updated}), 200


@shop_bp.route("/api/v1/admin/shop/products/bulk-deactivate", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_bulk_deactivate_products():
    """Bulk deactivate products."""
    data = request.get_json() or {}
    product_ids = data.get("product_ids", [])
    repo = ProductRepository(db.session)
    updated = 0
    for pid in product_ids:
        product = repo.find_by_id(pid)
        if product:
            product.is_active = False
            repo.save(product)
            updated += 1
    return jsonify({"updated": updated}), 200


# ── Public: Cart Checkout ────────────────────────────────────────────


@shop_bp.route("/api/v1/shop/cart/checkout", methods=["POST"])
@require_auth
def cart_checkout():
    """Block stock and create invoice from cart items."""
    from plugins.shop.shop.services.stock_service import (
        StockService,
        InsufficientStockError,
    )
    from plugins.shop.shop.repositories.stock_block_repository import (
        StockBlockRepository,
    )
    from vbwd.models.enums import InvoiceStatus, LineItemType
    from vbwd.models.invoice import UserInvoice
    from vbwd.models.invoice_line_item import InvoiceLineItem
    from vbwd.services.invoice_line_item_snapshot import (
        snapshot_line_item_tags_and_custom_fields,
    )
    from decimal import Decimal, ROUND_HALF_UP
    import uuid

    data = request.get_json() or {}
    items = data.get("items", [])
    coupon_code = data.get("coupon_code")
    if not items:
        return jsonify({"error": "Cart is empty"}), 400

    # S101.0: run any registered checkout validators (e.g. a downstream module's
    # class-based purchase gate) BEFORE blocking stock or creating the invoice —
    # fail closed. Shop ships no validators; it only runs what's registered.
    from plugins.shop.shop.checkout_validation_registry import (
        CheckoutValidationError,
        get_checkout_validation_registry,
    )

    try:
        get_checkout_validation_registry().validate(items=items, user_id=g.user_id)
    except CheckoutValidationError as validation_error:
        return jsonify({"error": validation_error.reason}), 400

    product_repo = ProductRepository(db.session)
    stock_service = StockService(
        WarehouseStockRepository(db.session),
        StockBlockRepository(db.session),
    )

    # Pre-validate the coupon against the cart subtotal BEFORE creating the
    # invoice / blocking stock — block_stock commits, so a later rollback can't
    # undo a rejected checkout. The discount line is added after the loop.
    from vbwd.services.checkout_price_adjustment_registry import (
        resolve_price_adjustment,
    )
    from vbwd.services.core_settings_store import get_default_currency

    # S99: the billing currency is the operating currency (the configured
    # default) — both the coupon scope and the invoice are denominated in it,
    # never a hard-coded literal.
    billing_currency = get_default_currency()

    # S85.2 (D1/D8): all price math goes through the core PriceFactory. The
    # charge per item is Price.brutto; the breakdown (netto + per-tax) is what
    # the line item records.
    price_factory = current_app.container.price_factory()

    preview_subtotal = Decimal("0")
    for cart_item in items:
        preview_product = product_repo.find_by_id(cart_item["product_id"])
        if preview_product:
            # S85.2 (D8): the charge is the computed brutto; cast to Decimal so
            # the coupon preview math stays exact (no float/Decimal mixing).
            brutto = Decimal(
                str(price_factory.get_price_from_object(preview_product).brutto)
            )
            preview_subtotal += brutto * int(cart_item.get("quantity", 1))

    price_result = resolve_price_adjustment(
        code=coupon_code,
        subtotal=preview_subtotal,
        user_id=str(g.user_id) if g.user_id else None,
        scope="ECOMMERCE",
        currency=billing_currency,
    )
    if not price_result.valid:
        return (
            jsonify({"error": price_result.error or "Coupon is not valid"}),
            400,
        )

    # Create invoice
    invoice = UserInvoice()
    invoice.user_id = g.user_id
    invoice.invoice_number = f"SH-{uuid.uuid4().hex[:8].upper()}"
    invoice.currency = billing_currency
    invoice.status = InvoiceStatus.PENDING
    invoice.amount = Decimal("0")
    invoice.subtotal = Decimal("0")
    invoice.total_amount = Decimal("0")
    from vbwd.utils.datetime_utils import utcnow

    invoice.invoiced_at = utcnow()
    total = Decimal("0")
    # S85.4: roll the net / Σtax up from the per-line tax fields so the invoice
    # carries a real tax split (the discount line has no breakdown → net only).
    invoice_net = Decimal("0")
    invoice_tax = Decimal("0")

    db.session.add(invoice)
    db.session.flush()

    session_id = str(invoice.id)
    from vbwd.pricing.line_tax_fields import line_tax_fields

    product_line_items = []
    try:
        for cart_item in items:
            product = product_repo.find_by_id(cart_item["product_id"])
            if not product:
                db.session.rollback()
                return (
                    jsonify({"error": f"Product {cart_item['product_id']} not found"}),
                    400,
                )

            quantity = int(cart_item.get("quantity", 1))
            variant_id = cart_item.get("variant_id")

            # Block stock
            stock_service.block_stock(
                product_id=product.id,
                quantity=quantity,
                session_id=session_id,
                variant_id=variant_id,
            )

            # S85.2 (D8): the charged unit price is the computed brutto. The
            # invoice is an immutable financial record (Numeric(10,2) columns),
            # so the brutto float is quantized to cents HERE — the one legitimate
            # rounding boundary. The live Price VO stays full-precision (D4).
            computed_price = price_factory.get_price_from_object(product)
            unit_price = Decimal(str(computed_price.brutto)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            line_total = unit_price * quantity
            total += line_total

            line_item = InvoiceLineItem()
            line_item.id = uuid.uuid4()
            line_item.invoice_id = invoice.id
            line_item.item_type = LineItemType.CUSTOM
            line_item.item_id = product.id
            line_item.description = f"{product.name}"
            line_item.quantity = quantity
            line_item.unit_price = unit_price
            line_item.total_price = line_total
            # S85.4: persist the per-rate split as first-class columns (quantity
            # scales the amounts). Roll the invoice net / tax up from these.
            tax_fields = line_tax_fields(computed_price, quantity=quantity)
            line_item.net_amount = tax_fields["net_amount"]
            line_item.tax_amount = tax_fields["tax_amount"]
            line_item.tax_breakdown = tax_fields["tax_breakdown"]
            invoice_net += tax_fields["net_amount"]
            invoice_tax += tax_fields["tax_amount"]
            line_item.extra_data = {
                "plugin": "shop",
                "product_id": str(product.id),
                "product_slug": product.slug,
                "product_name": product.name,
                "product_sku": product.sku,
                "is_digital": product.is_digital,
                "variant_id": str(variant_id) if variant_id else None,
                "quantity": quantity,
                # S85.2: persist the per-line netto + per-tax breakdown from the
                # Price VO. Invoices are an immutable financial record; these
                # values are the recorded tax split for the charged brutto.
                "price_breakdown": computed_price.to_dict(),
            }
            db.session.add(line_item)
            product_line_items.append(line_item)
            # S77: freeze the product's tags + custom-fields onto the line item
            # so the invoice stays immutable (no live join to the product).
            snapshot_line_item_tags_and_custom_fields(line_item)

        # Apply the (already-validated) coupon discount as a negative line.
        # S96.6 (D-DiscountTax): the coupon quotes a GROSS discount that reduces
        # the NETTO; the tax recomputes on the discounted netto. The discount
        # line carries negative net_amount / tax_amount / per-rate tax_breakdown
        # (split proportionally to the AGGREGATED pre-discount per-rate tax across
        # all product lines). The invoice subtotal / tax_amount / total_amount
        # then ROLL UP from all lines so the four invariants hold to the cent.
        if price_result.discount_amount > Decimal("0"):
            gross_discount = Decimal(str(price_result.discount_amount))
            pre_discount_net = invoice_net
            pre_discount_total = invoice_net + invoice_tax

            # Split the gross discount into its netto / tax portions in proportion
            # to the order's pre-discount split (one cents rounding; tax = gross -
            # net so they always sum to the gross discount).
            if pre_discount_total > Decimal("0"):
                net_discount = (
                    gross_discount * pre_discount_net / pre_discount_total
                ).quantize(_CENTS, rounding=ROUND_HALF_UP)
            else:
                net_discount = gross_discount
            tax_discount = gross_discount - net_discount

            aggregated_breakdown = _aggregate_pre_discount_tax_breakdown(
                product_line_items
            )
            discount_breakdown = _split_discount_tax_breakdown(
                aggregated_breakdown, tax_discount
            )

            discount_line = InvoiceLineItem()
            discount_line.invoice_id = invoice.id
            discount_line.item_type = LineItemType.CUSTOM
            discount_line.item_id = uuid.uuid4()
            discount_line.description = price_result.label or "Discount"
            discount_line.quantity = 1
            discount_line.unit_price = -gross_discount
            discount_line.total_price = -gross_discount
            discount_line.net_amount = -net_discount
            discount_line.tax_amount = -tax_discount
            discount_line.tax_breakdown = discount_breakdown
            discount_line.extra_data = {"discount": True, "coupon_code": coupon_code}
            db.session.add(discount_line)

            total -= gross_discount
            invoice_net -= net_discount
            invoice_tax -= tax_discount

        invoice.amount = total
        invoice.subtotal = invoice_net
        invoice.tax_amount = invoice_tax
        invoice.total_amount = total
        db.session.commit()

        # Redeem the coupon + record the application once the invoice persists.
        if price_result.on_committed:
            price_result.on_committed(str(invoice.id), str(g.user_id))

        return (
            jsonify(
                {
                    "invoice_id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "total": str(total),
                }
            ),
            201,
        )

    except InsufficientStockError as stock_error:
        db.session.rollback()
        return jsonify({"error": str(stock_error)}), 400


# ── Admin: Shipping Methods ─────────────────────────────────────────


def _shipping_registry():
    from plugins.shop import _shipping_registry as reg

    return reg


@shop_bp.route("/api/v1/admin/shop/shipping/methods", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.configure")
def admin_list_shipping_methods():
    """List all registered shipping methods."""
    registry = _shipping_registry()
    return jsonify({"methods": registry.get_all()}), 200


@shop_bp.route(
    "/api/v1/admin/shop/shipping/methods/<slug>/toggle",
    methods=["POST"],
)
@require_auth
@require_admin
@require_permission("shop.configure")
def admin_toggle_shipping_method(slug):
    """Enable or disable a shipping method."""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    registry = _shipping_registry()

    if enabled:
        ok = registry.enable(slug)
    else:
        ok = registry.disable(slug)

    if not ok:
        return jsonify({"error": "Cannot toggle this method"}), 400

    return jsonify({"slug": slug, "enabled": enabled}), 200


@shop_bp.route(
    "/api/v1/admin/shop/shipping/rates",
    methods=["POST"],
)
@require_auth
@require_admin
@require_permission("shop.configure")
def admin_calculate_shipping_rates():
    """Preview shipping rates for given items + address."""
    data = request.get_json() or {}
    items = data.get("items", [])
    address = data.get("address", {})
    # S99: shipping cost is denominated in the operating (billing) currency —
    # read the setting, never a literal fallback.
    from vbwd.services.core_settings_store import get_default_currency

    currency = data.get("currency") or get_default_currency()

    registry = _shipping_registry()
    all_rates = []
    for provider in registry.get_enabled():
        try:
            rates = provider.calculate_rate(items, address, currency)
            for rate in rates:
                all_rates.append(
                    {
                        "provider": rate.provider_slug,
                        "name": rate.name,
                        "cost": str(rate.cost),
                        "currency": rate.currency,
                        "estimated_days": rate.estimated_days,
                        "description": rate.description,
                    }
                )
        except Exception:
            pass  # Provider error — skip

    return jsonify({"rates": all_rates}), 200


# ── Admin: Product variants (S101.0) ──────────────────────────────────────


def _variant_service():
    """Build the variant-authoring service with a request-scoped session."""
    from plugins.shop.shop.repositories.product_variant_repository import (
        ProductVariantRepository,
    )
    from plugins.shop.shop.services.product_variant_service import (
        ProductVariantService,
    )

    return ProductVariantService(
        ProductVariantRepository(db.session),
        current_app.container.price_factory(),
    )


def _variant_payload(service, variant):
    """Serialise a variant with its ``PriceFactory``-computed pricing block."""
    payload = variant.to_dict()
    payload["pricing"] = service.get_variant_pricing(variant)
    return payload


@shop_bp.route("/api/v1/admin/shop/products/<product_id>/variants", methods=["GET"])
@require_auth
@require_admin
@require_permission("shop.products.view")
def admin_list_variants(product_id):
    """List a product's variants (ordered)."""
    product = ProductRepository(db.session).find_by_id(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    service = _variant_service()
    variants = service.list_variants(product.id)
    return (
        jsonify({"variants": [_variant_payload(service, v) for v in variants]}),
        200,
    )


@shop_bp.route("/api/v1/admin/shop/products/<product_id>/variants", methods=["POST"])
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_create_variant(product_id):
    """Create a pack/strength/form variant for a product."""
    from plugins.shop.shop.services.product_variant_service import (
        DuplicateVariantSkuError,
    )

    product = ProductRepository(db.session).find_by_id(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    data = request.get_json() or {}
    service = _variant_service()
    try:
        variant = service.create_variant(product.id, data)
    except DuplicateVariantSkuError as error:
        return jsonify({"error": str(error)}), 400
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    # A product with variants must advertise that so the detail route nests them.
    if not product.has_variants:
        product.has_variants = True
        ProductRepository(db.session).save(product)

    return jsonify({"variant": _variant_payload(service, variant)}), 201


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/variants/<variant_id>",
    methods=["PUT"],
)
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_update_variant(product_id, variant_id):
    """Update a variant's editable attributes."""
    from plugins.shop.shop.services.product_variant_service import (
        DuplicateVariantSkuError,
        VariantNotFoundError,
    )

    data = request.get_json() or {}
    service = _variant_service()
    try:
        variant = service.update_variant(product_id, variant_id, data)
    except VariantNotFoundError:
        return jsonify({"error": "Variant not found"}), 404
    except DuplicateVariantSkuError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"variant": _variant_payload(service, variant)}), 200


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/variants/<variant_id>",
    methods=["DELETE"],
)
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_delete_variant(product_id, variant_id):
    """Delete a variant."""
    from plugins.shop.shop.services.product_variant_service import (
        VariantNotFoundError,
    )

    service = _variant_service()
    try:
        service.delete_variant(product_id, variant_id)
    except VariantNotFoundError:
        return jsonify({"error": "Variant not found"}), 404
    return jsonify({"message": "Variant deleted"}), 200


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/variants/reorder",
    methods=["POST"],
)
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_reorder_variants(product_id):
    """Reorder a product's variants by an ordered list of variant ids."""
    from plugins.shop.shop.services.product_variant_service import (
        VariantNotFoundError,
    )

    data = request.get_json() or {}
    ordered_ids = data.get("variant_ids") or []
    service = _variant_service()
    try:
        variants = service.reorder_variants(product_id, ordered_ids)
    except VariantNotFoundError as error:
        return jsonify({"error": str(error)}), 400
    return (
        jsonify({"variants": [_variant_payload(service, v) for v in variants]}),
        200,
    )


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/variants/<variant_id>/toggle",
    methods=["POST"],
)
@require_auth
@require_admin
@require_permission("shop.products.manage")
def admin_toggle_variant(product_id, variant_id):
    """Flip a variant's ``is_active`` flag."""
    from plugins.shop.shop.services.product_variant_service import (
        VariantNotFoundError,
    )

    service = _variant_service()
    try:
        variant = service.toggle_variant(product_id, variant_id)
    except VariantNotFoundError:
        return jsonify({"error": "Variant not found"}), 404
    return jsonify({"variant": _variant_payload(service, variant)}), 200
