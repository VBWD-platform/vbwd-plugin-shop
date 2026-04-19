"""E-commerce routes — public catalog + admin management."""
from flask import Blueprint, jsonify, request, g
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

shop_bp = Blueprint("shop", __name__)


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

    return jsonify({
        "products": [p.to_dict() for p in products],
        "page": page,
        "per_page": per_page,
        "total": repo.count_active(),
    }), 200


@shop_bp.route("/api/v1/shop/products/<slug>", methods=["GET"])
def get_product(slug):
    """Product detail with images, variants, stock status."""
    repo = ProductRepository(db.session)
    product = repo.find_by_slug(slug)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    stock_repo = WarehouseStockRepository(db.session)
    product_dict = product.to_dict()

    if product.has_variants:
        for variant in product_dict.get("variants", []):
            from uuid import UUID
            available = stock_repo.get_total_available(
                product.id, UUID(variant["id"])
            )
            variant["stock_available"] = available
    else:
        product_dict["stock_available"] = stock_repo.get_total_available(product.id)

    return jsonify({"product": product_dict}), 200


@shop_bp.route("/api/v1/shop/categories", methods=["GET"])
def list_categories():
    """Category tree."""
    repo = ProductCategoryRepository(db.session)
    categories = repo.find_root_categories()
    return jsonify({
        "categories": [c.to_dict() for c in categories],
    }), 200


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
    return jsonify({
        "orders": [o.to_dict() for o in orders],
        "total": repo.count_by_user(g.user_id),
    }), 200


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
    return jsonify({
        "products": [p.to_dict() for p in products],
        "page": page,
        "per_page": per_page,
    }), 200


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

    product = Product(
        id=uuid4(),
        name=data["name"],
        slug=slug,
        description=data.get("description"),
        sku=data.get("sku"),
        price=data.get("price", 0),
        currency=data.get("currency", "EUR"),
        price_float=float(data.get("price", 0)),
        is_active=data.get("is_active", True),
        is_digital=data.get("is_digital", False),
        has_variants=data.get("has_variants", False),
        weight=data.get("weight"),
        dimensions=data.get("dimensions", {}),
        tax_class=data.get("tax_class", "standard"),
    )
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
    for field_name in ["name", "description", "sku", "price", "currency", "is_active",
                       "is_digital", "has_variants", "weight", "dimensions", "tax_class"]:
        if field_name in data:
            setattr(product, field_name, data[field_name])
    if "price" in data:
        product.price_float = float(data["price"])

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

    return jsonify({
        "orders": [o.to_dict() for o in orders],
        "page": page,
        "per_page": per_page,
    }), 200


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
    warehouse_stock = [s.to_dict() for s in stock_items if str(s.warehouse_id) == str(warehouse_id)]

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
    for field_name in ["name", "slug", "description", "image_url", "parent_id", "sort_order"]:
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
    try:
        from plugins.cms.src.services.cms_image_service import CmsImageService  # noqa: F401
        return True
    except ImportError:
        return False


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/images", methods=["GET"]
)
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


@shop_bp.route(
    "/api/v1/admin/shop/products/<product_id>/images", methods=["POST"]
)
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
    from plugins.cms.src.services.file_storage import LocalFileStorage
    from plugins.shop.shop.models.product_image import ProductImage

    image_repo = CmsImageRepository(db.session)
    storage = LocalFileStorage(base_path="/app/uploads", base_url="/uploads")
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
    from decimal import Decimal
    import uuid

    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Cart is empty"}), 400

    product_repo = ProductRepository(db.session)
    stock_service = StockService(
        WarehouseStockRepository(db.session),
        StockBlockRepository(db.session),
    )

    # Create invoice
    invoice = UserInvoice()
    invoice.user_id = g.user_id
    invoice.invoice_number = f"SH-{uuid.uuid4().hex[:8].upper()}"
    invoice.currency = "EUR"
    invoice.status = InvoiceStatus.PENDING
    invoice.amount = Decimal("0")
    invoice.subtotal = Decimal("0")
    invoice.total_amount = Decimal("0")
    from vbwd.utils.datetime_utils import utcnow
    invoice.invoiced_at = utcnow()
    total = Decimal("0")

    db.session.add(invoice)
    db.session.flush()

    session_id = str(invoice.id)

    try:
        for cart_item in items:
            product = product_repo.find_by_id(cart_item["product_id"])
            if not product:
                db.session.rollback()
                return jsonify({"error": f"Product {cart_item['product_id']} not found"}), 400

            quantity = int(cart_item.get("quantity", 1))
            variant_id = cart_item.get("variant_id")

            # Block stock
            stock_service.block_stock(
                product_id=product.id,
                quantity=quantity,
                session_id=session_id,
                variant_id=variant_id,
            )

            unit_price = product.price
            line_total = unit_price * quantity
            total += line_total

            line_item = InvoiceLineItem()
            line_item.invoice_id = invoice.id
            line_item.item_type = LineItemType.CUSTOM
            line_item.item_id = product.id
            line_item.description = f"{product.name}"
            line_item.quantity = quantity
            line_item.unit_price = unit_price
            line_item.total_price = line_total
            line_item.extra_data = {
                "plugin": "shop",
                "product_id": str(product.id),
                "product_slug": product.slug,
                "product_name": product.name,
                "product_sku": product.sku,
                "is_digital": product.is_digital,
                "variant_id": str(variant_id) if variant_id else None,
                "quantity": quantity,
            }
            db.session.add(line_item)

        invoice.amount = total
        invoice.subtotal = total
        invoice.total_amount = total
        db.session.commit()

        return jsonify({
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "total": str(total),
        }), 201

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
    currency = data.get("currency", "EUR")

    registry = _shipping_registry()
    all_rates = []
    for provider in registry.get_enabled():
        try:
            rates = provider.calculate_rate(items, address, currency)
            for rate in rates:
                all_rates.append({
                    "provider": rate.provider_slug,
                    "name": rate.name,
                    "cost": str(rate.cost),
                    "currency": rate.currency,
                    "estimated_days": rate.estimated_days,
                    "description": rate.description,
                })
        except Exception:
            pass  # Provider error — skip

    return jsonify({"rates": all_rates}), 200
