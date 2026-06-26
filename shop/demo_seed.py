"""Shop demo catalog seed — the single home for the shop seed logic (S88).

``seed_catalog(session)`` is registered into core's demo-data registry from the
plugin's ``on_enable`` so ``flask reset-demo`` seeds the shop catalog + CMS
content through the same agnostic seam every other plugin uses. The standalone
``plugins/shop/populate_db.py`` is a thin wrapper over this function (DRY: one
seed home).

Idempotent: every row is upserted by slug/sku, so a re-run creates nothing new.
"""
import logging
from decimal import Decimal
from uuid import uuid4

from vbwd.services.demo_tax_linker import link_demo_tax

logger = logging.getLogger(__name__)


def seed_catalog(session) -> dict:
    """Seed the shop catalog (warehouse, categories, products, variants,
    images, stock) + CMS content + email templates through ``session``.

    Returns a small stats dict for the reset-demo summary.
    """
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.product_variant import ProductVariant
    from plugins.shop.shop.models.product_image import ProductImage
    from plugins.shop.shop.models.product_category import ProductCategory
    from plugins.shop.shop.models.warehouse import Warehouse
    from plugins.shop.shop.models.warehouse_stock import WarehouseStock

    created_count = _seed_warehouse_products(
        session,
        Product,
        ProductVariant,
        ProductImage,
        ProductCategory,
        Warehouse,
        WarehouseStock,
    )

    _link_product_taxes(session)
    _populate_cms_content(session)
    _populate_email_templates(session)

    return {
        "shop_products": session.query(Product).count(),
        "shop_products_created": created_count,
    }


def _link_product_taxes(session) -> None:
    """Link the canonical demo VAT to every demo product (S85.4).

    Runs independently of product creation: products are skipped on a re-run,
    but the tax link must still be ensured. Idempotent (the core linker does not
    double-link) and a no-op when the canonical VAT is absent. The tax is
    resolved by code through the core linker — no cross-plugin import.
    """
    from plugins.shop.shop.models.product import Product

    products = []
    for product_data in _products_data():
        product = session.query(Product).filter_by(slug=product_data["slug"]).first()
        if product is not None:
            products.append(product)

    link_demo_tax(session, products)


def _seed_warehouse_products(
    session,
    Product,
    ProductVariant,
    ProductImage,
    ProductCategory,
    Warehouse,
    WarehouseStock,
) -> int:
    created_count = 0

    # --- Warehouse ---
    warehouse = session.query(Warehouse).filter_by(slug="main-warehouse").first()
    if not warehouse:
        warehouse = Warehouse(
            id=uuid4(),
            name="Main Warehouse",
            slug="main-warehouse",
            address={
                "street": "123 Commerce St",
                "city": "Berlin",
                "country": "DE",
                "zip": "10115",
            },
            is_active=True,
            is_default=True,
        )
        session.add(warehouse)
        session.flush()
        created_count += 1
        logger.info("[shop] Created warehouse: main-warehouse")

    # --- Categories (8 total, 4 subcategories) ---
    def _cat(slug, name, desc, parent_slug=None, sort=0):
        return {
            "slug": slug,
            "name": name,
            "description": desc,
            "parent_slug": parent_slug,
            "sort_order": sort,
        }

    categories_data = [
        _cat("electronics", "Electronics", "Gadgets, devices and accessories", sort=0),
        _cat(
            "audio", "Audio", "Headphones, speakers and microphones", "electronics", 0
        ),
        _cat(
            "cables-adapters",
            "Cables & Adapters",
            "USB, HDMI, and power cables",
            "electronics",
            1,
        ),
        _cat("clothing", "Clothing", "Fashion and apparel", sort=1),
        _cat("mens", "Men's", "Men's clothing", "clothing", 0),
        _cat("womens", "Women's", "Women's clothing", "clothing", 1),
        _cat("books", "Books", "Physical and digital books", sort=2),
        _cat(
            "home-garden", "Home & Garden", "Furniture, decor and garden tools", sort=3
        ),
    ]

    category_map = {}
    for cat_data in categories_data:
        existing = (
            session.query(ProductCategory).filter_by(slug=cat_data["slug"]).first()
        )
        if not existing:
            parent_id = (
                category_map[cat_data["parent_slug"]].id
                if cat_data.get("parent_slug")
                else None
            )
            category = ProductCategory(
                id=uuid4(),
                name=cat_data["name"],
                slug=cat_data["slug"],
                description=cat_data["description"],
                parent_id=parent_id,
                sort_order=cat_data["sort_order"],
            )
            session.add(category)
            session.flush()
            category_map[cat_data["slug"]] = category
            created_count += 1
        else:
            category_map[cat_data["slug"]] = existing

    # --- Products (50 SKUs with variants and images) ---
    IMG = "https://placehold.co"  # Placeholder image service

    products_data = _products_data()

    for product_data in products_data:
        existing = session.query(Product).filter_by(slug=product_data["slug"]).first()
        if existing:
            continue

        has_variants = "variants" in product_data
        product = Product(
            id=uuid4(),
            name=product_data["name"],
            slug=product_data["slug"],
            description=product_data.get("desc", ""),
            sku=product_data["sku"],
            price=float(product_data["price"]),
            is_active=True,
            is_digital=product_data.get("is_digital", False),
            has_variants=has_variants,
            weight=product_data.get("weight"),
            tax_class="standard",
        )
        session.add(product)
        session.flush()

        # Assign category
        cat_slug = product_data.get("cat")
        if cat_slug and cat_slug in category_map:
            category_map[cat_slug].products.append(product)

        # Create variants
        for variant_data in product_data.get("variants", []):
            variant = ProductVariant(
                id=uuid4(),
                product_id=product.id,
                name=variant_data["name"],
                sku=variant_data["sku"],
                attributes=variant_data.get("attrs", {}),
                is_active=True,
            )
            session.add(variant)
            session.flush()
            if variant_data.get("stock") is not None:
                session.add(
                    WarehouseStock(
                        id=uuid4(),
                        warehouse_id=warehouse.id,
                        product_id=product.id,
                        variant_id=variant.id,
                        quantity=variant_data["stock"],
                    )
                )

        # Stock for non-variant products
        stock_qty = product_data.get("stock")
        if not has_variants and stock_qty is not None:
            session.add(
                WarehouseStock(
                    id=uuid4(),
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    quantity=stock_qty,
                )
            )

        # Product images (5 per product using placeholder service)
        colors = ["4A90D9", "E74C3C", "2ECC71", "F39C12", "9B59B6"]
        for img_index in range(5):
            width = 600 if img_index == 0 else 400
            session.add(
                ProductImage(
                    id=uuid4(),
                    product_id=product.id,
                    url=(
                        f"{IMG}/{width}x{width}/{colors[img_index]}/FFFFFF"
                        f"?text={product_data['sku']}+img{img_index + 1}"
                    ),
                    alt=f"{product_data['name']} - image {img_index + 1}",
                    sort_order=img_index,
                    is_primary=(img_index == 0),
                )
            )

        created_count += 1

    if created_count:
        session.commit()
        logger.info("[shop] seed_catalog: created %d records", created_count)
    else:
        logger.info("[shop] seed_catalog: all data already exists")
    return created_count


def _products_data():
    """The 50-SKU demo product catalogue (data only — no DB access)."""
    return [
        # ── Audio (subcategory of Electronics) ──
        {
            "name": "Wireless Headphones Pro",
            "slug": "wireless-headphones-pro",
            "sku": "AUD-WHP-001",
            "price": Decimal("89.99"),
            "cat": "audio",
            "weight": Decimal("0.28"),
            "desc": "Premium ANC headphones, 40h battery, Bluetooth 5.3.",
            "variants": [
                {
                    "name": "Midnight Black",
                    "sku": "AUD-WHP-001-BLK",
                    "attrs": {"color": "Black"},
                    "stock": 40,
                },
                {
                    "name": "Arctic White",
                    "sku": "AUD-WHP-001-WHT",
                    "attrs": {"color": "White"},
                    "stock": 30,
                },
                {
                    "name": "Navy Blue",
                    "sku": "AUD-WHP-001-NVY",
                    "attrs": {"color": "Navy"},
                    "stock": 20,
                },
            ],
        },
        {
            "name": "Wireless Earbuds",
            "slug": "wireless-earbuds",
            "sku": "AUD-WEB-001",
            "price": Decimal("49.99"),
            "cat": "audio",
            "weight": Decimal("0.05"),
            "desc": "Compact true wireless earbuds with charging case.",
            "stock": 120,
        },
        {
            "name": "Portable Bluetooth Speaker",
            "slug": "bluetooth-speaker",
            "sku": "AUD-BTS-001",
            "price": Decimal("39.99"),
            "cat": "audio",
            "weight": Decimal("0.45"),
            "desc": "Waterproof IPX7 speaker, 12h playtime.",
            "variants": [
                {
                    "name": "Black",
                    "sku": "AUD-BTS-001-BLK",
                    "attrs": {"color": "Black"},
                    "stock": 50,
                },
                {
                    "name": "Red",
                    "sku": "AUD-BTS-001-RED",
                    "attrs": {"color": "Red"},
                    "stock": 35,
                },
            ],
        },
        {
            "name": "Studio Monitor Headphones",
            "slug": "studio-monitors",
            "sku": "AUD-SMH-001",
            "price": Decimal("149.99"),
            "cat": "audio",
            "weight": Decimal("0.35"),
            "desc": "Reference-grade open-back headphones for mixing.",
            "stock": 25,
        },
        {
            "name": "USB Condenser Microphone",
            "slug": "usb-microphone",
            "sku": "AUD-UCM-001",
            "price": Decimal("69.99"),
            "cat": "audio",
            "weight": Decimal("0.60"),
            "desc": "Cardioid condenser mic for streaming and podcasting.",
            "stock": 60,
        },
        # ── Cables & Adapters ──
        {
            "name": "USB-C Cable 2m",
            "slug": "usb-c-cable-2m",
            "sku": "CBL-UC2-001",
            "price": Decimal("12.99"),
            "cat": "cables-adapters",
            "weight": Decimal("0.05"),
            "desc": "Braided USB-C to USB-C cable, 100W PD.",
            "stock": 300,
        },
        {
            "name": "USB-C Hub 7-in-1",
            "slug": "usb-c-hub-7in1",
            "sku": "CBL-HUB-001",
            "price": Decimal("34.99"),
            "cat": "cables-adapters",
            "weight": Decimal("0.12"),
            "desc": "HDMI 4K, USB 3.0, SD card, PD passthrough.",
            "stock": 80,
        },
        {
            "name": "HDMI Cable 3m",
            "slug": "hdmi-cable-3m",
            "sku": "CBL-HDM-001",
            "price": Decimal("9.99"),
            "cat": "cables-adapters",
            "weight": Decimal("0.08"),
            "desc": "HDMI 2.1, 8K@60Hz, eARC support.",
            "stock": 200,
        },
        {
            "name": "Lightning to USB-C Adapter",
            "slug": "lightning-usbc-adapter",
            "sku": "CBL-LUC-001",
            "price": Decimal("7.99"),
            "cat": "cables-adapters",
            "weight": Decimal("0.01"),
            "desc": "Compact adapter for legacy devices.",
            "stock": 150,
        },
        {
            "name": "Wireless Charging Pad",
            "slug": "wireless-charger",
            "sku": "CBL-WCP-001",
            "price": Decimal("19.99"),
            "cat": "cables-adapters",
            "weight": Decimal("0.10"),
            "desc": "15W Qi charger with LED indicator.",
            "stock": 100,
        },
        # ── Electronics (parent) ──
        {
            "name": "Smart Watch Fitness",
            "slug": "smart-watch-fitness",
            "sku": "ELEC-SWF-001",
            "price": Decimal("129.99"),
            "cat": "electronics",
            "weight": Decimal("0.06"),
            "desc": "Heart rate, GPS, 7-day battery, water resistant.",
            "variants": [
                {
                    "name": "42mm Black",
                    "sku": "ELEC-SWF-001-42B",
                    "attrs": {"size": "42mm", "color": "Black"},
                    "stock": 30,
                },
                {
                    "name": "42mm Silver",
                    "sku": "ELEC-SWF-001-42S",
                    "attrs": {"size": "42mm", "color": "Silver"},
                    "stock": 25,
                },
                {
                    "name": "46mm Black",
                    "sku": "ELEC-SWF-001-46B",
                    "attrs": {"size": "46mm", "color": "Black"},
                    "stock": 20,
                },
            ],
        },
        {
            "name": "Mechanical Keyboard",
            "slug": "mechanical-keyboard",
            "sku": "ELEC-MKB-001",
            "price": Decimal("79.99"),
            "cat": "electronics",
            "weight": Decimal("0.85"),
            "desc": "Hot-swappable switches, RGB backlight, 75% layout.",
            "variants": [
                {
                    "name": "Red Switch",
                    "sku": "ELEC-MKB-001-RED",
                    "attrs": {"switch": "Red (Linear)"},
                    "stock": 40,
                },
                {
                    "name": "Brown Switch",
                    "sku": "ELEC-MKB-001-BRN",
                    "attrs": {"switch": "Brown (Tactile)"},
                    "stock": 35,
                },
                {
                    "name": "Blue Switch",
                    "sku": "ELEC-MKB-001-BLU",
                    "attrs": {"switch": "Blue (Clicky)"},
                    "stock": 25,
                },
            ],
        },
        {
            "name": "Ergonomic Mouse",
            "slug": "ergonomic-mouse",
            "sku": "ELEC-ERM-001",
            "price": Decimal("44.99"),
            "cat": "electronics",
            "weight": Decimal("0.12"),
            "desc": "Vertical design, 6 buttons, 4000 DPI.",
            "stock": 90,
        },
        {
            "name": "Webcam 4K",
            "slug": "webcam-4k",
            "sku": "ELEC-WC4-001",
            "price": Decimal("59.99"),
            "cat": "electronics",
            "weight": Decimal("0.15"),
            "desc": "Autofocus, noise-cancelling mic, privacy shutter.",
            "stock": 55,
        },
        {
            "name": "Power Bank 20000mAh",
            "slug": "power-bank-20k",
            "sku": "ELEC-PBK-001",
            "price": Decimal("29.99"),
            "cat": "electronics",
            "weight": Decimal("0.40"),
            "desc": "PD 65W output, dual USB-C ports.",
            "stock": 110,
        },
        {
            "name": "E-Reader 7 inch",
            "slug": "e-reader-7",
            "sku": "ELEC-ERD-001",
            "price": Decimal("119.99"),
            "cat": "electronics",
            "weight": Decimal("0.18"),
            "desc": "E-ink display, front light, 32GB storage.",
            "stock": 40,
        },
        # ── Men's Clothing ──
        {
            "name": "Cotton T-Shirt Classic",
            "slug": "cotton-tshirt-classic",
            "sku": "MEN-CTS-001",
            "price": Decimal("24.99"),
            "cat": "mens",
            "weight": Decimal("0.20"),
            "desc": "100% organic cotton, pre-shrunk.",
            "variants": [
                {
                    "name": "S / White",
                    "sku": "MEN-CTS-001-SW",
                    "attrs": {"size": "S", "color": "White"},
                    "stock": 30,
                },
                {
                    "name": "M / White",
                    "sku": "MEN-CTS-001-MW",
                    "attrs": {"size": "M", "color": "White"},
                    "stock": 40,
                },
                {
                    "name": "L / White",
                    "sku": "MEN-CTS-001-LW",
                    "attrs": {"size": "L", "color": "White"},
                    "stock": 35,
                },
                {
                    "name": "M / Black",
                    "sku": "MEN-CTS-001-MB",
                    "attrs": {"size": "M", "color": "Black"},
                    "stock": 40,
                },
                {
                    "name": "L / Black",
                    "sku": "MEN-CTS-001-LB",
                    "attrs": {"size": "L", "color": "Black"},
                    "stock": 30,
                },
            ],
        },
        {
            "name": "Slim Fit Jeans",
            "slug": "slim-fit-jeans",
            "sku": "MEN-SFJ-001",
            "price": Decimal("49.99"),
            "cat": "mens",
            "weight": Decimal("0.55"),
            "desc": "Stretch denim, mid-rise, tapered leg.",
            "variants": [
                {
                    "name": "30/32 Indigo",
                    "sku": "MEN-SFJ-001-30I",
                    "attrs": {"waist": "30", "length": "32", "color": "Indigo"},
                    "stock": 20,
                },
                {
                    "name": "32/32 Indigo",
                    "sku": "MEN-SFJ-001-32I",
                    "attrs": {"waist": "32", "length": "32", "color": "Indigo"},
                    "stock": 25,
                },
                {
                    "name": "34/32 Indigo",
                    "sku": "MEN-SFJ-001-34I",
                    "attrs": {"waist": "34", "length": "32", "color": "Indigo"},
                    "stock": 20,
                },
                {
                    "name": "32/32 Black",
                    "sku": "MEN-SFJ-001-32B",
                    "attrs": {"waist": "32", "length": "32", "color": "Black"},
                    "stock": 15,
                },
            ],
        },
        {
            "name": "Hoodie Zip-Up",
            "slug": "hoodie-zipup",
            "sku": "MEN-HZU-001",
            "price": Decimal("39.99"),
            "cat": "mens",
            "weight": Decimal("0.45"),
            "desc": "Fleece-lined, front zip, kangaroo pocket.",
            "variants": [
                {
                    "name": "M / Grey",
                    "sku": "MEN-HZU-001-MG",
                    "attrs": {"size": "M", "color": "Grey"},
                    "stock": 30,
                },
                {
                    "name": "L / Grey",
                    "sku": "MEN-HZU-001-LG",
                    "attrs": {"size": "L", "color": "Grey"},
                    "stock": 25,
                },
                {
                    "name": "L / Navy",
                    "sku": "MEN-HZU-001-LN",
                    "attrs": {"size": "L", "color": "Navy"},
                    "stock": 20,
                },
            ],
        },
        {
            "name": "Polo Shirt",
            "slug": "polo-shirt",
            "sku": "MEN-POL-001",
            "price": Decimal("34.99"),
            "cat": "mens",
            "weight": Decimal("0.22"),
            "desc": "Pique cotton, button-down collar.",
            "stock": 60,
        },
        {
            "name": "Chino Shorts",
            "slug": "chino-shorts",
            "sku": "MEN-CHS-001",
            "price": Decimal("29.99"),
            "cat": "mens",
            "weight": Decimal("0.30"),
            "desc": "Stretch cotton, 9 inch inseam.",
            "stock": 50,
        },
        # ── Women's Clothing ──
        {
            "name": "Floral Wrap Dress",
            "slug": "floral-wrap-dress",
            "sku": "WMN-FWD-001",
            "price": Decimal("59.99"),
            "cat": "womens",
            "weight": Decimal("0.30"),
            "desc": "V-neck, midi length, adjustable waist tie.",
            "variants": [
                {
                    "name": "S / Blue Floral",
                    "sku": "WMN-FWD-001-SB",
                    "attrs": {"size": "S", "color": "Blue Floral"},
                    "stock": 15,
                },
                {
                    "name": "M / Blue Floral",
                    "sku": "WMN-FWD-001-MB",
                    "attrs": {"size": "M", "color": "Blue Floral"},
                    "stock": 20,
                },
                {
                    "name": "M / Rose",
                    "sku": "WMN-FWD-001-MR",
                    "attrs": {"size": "M", "color": "Rose"},
                    "stock": 15,
                },
                {
                    "name": "L / Rose",
                    "sku": "WMN-FWD-001-LR",
                    "attrs": {"size": "L", "color": "Rose"},
                    "stock": 10,
                },
            ],
        },
        {
            "name": "Yoga Leggings",
            "slug": "yoga-leggings",
            "sku": "WMN-YGL-001",
            "price": Decimal("34.99"),
            "cat": "womens",
            "weight": Decimal("0.18"),
            "desc": "High-waist, 4-way stretch, moisture wicking.",
            "variants": [
                {
                    "name": "XS / Black",
                    "sku": "WMN-YGL-001-XSB",
                    "attrs": {"size": "XS", "color": "Black"},
                    "stock": 25,
                },
                {
                    "name": "S / Black",
                    "sku": "WMN-YGL-001-SB",
                    "attrs": {"size": "S", "color": "Black"},
                    "stock": 30,
                },
                {
                    "name": "M / Black",
                    "sku": "WMN-YGL-001-MB",
                    "attrs": {"size": "M", "color": "Black"},
                    "stock": 30,
                },
                {
                    "name": "M / Sage",
                    "sku": "WMN-YGL-001-MS",
                    "attrs": {"size": "M", "color": "Sage"},
                    "stock": 20,
                },
            ],
        },
        {
            "name": "Denim Jacket",
            "slug": "denim-jacket",
            "sku": "WMN-DNJ-001",
            "price": Decimal("69.99"),
            "cat": "womens",
            "weight": Decimal("0.65"),
            "desc": "Classic trucker style, button front.",
            "stock": 35,
        },
        {
            "name": "Silk Blouse",
            "slug": "silk-blouse",
            "sku": "WMN-SBL-001",
            "price": Decimal("54.99"),
            "cat": "womens",
            "weight": Decimal("0.15"),
            "desc": "100% mulberry silk, relaxed fit.",
            "stock": 25,
        },
        {
            "name": "Running Shoes",
            "slug": "running-shoes",
            "sku": "WMN-RNS-001",
            "price": Decimal("89.99"),
            "cat": "womens",
            "weight": Decimal("0.30"),
            "desc": "Lightweight mesh, cushioned sole.",
            "variants": [
                {
                    "name": "38 / White",
                    "sku": "WMN-RNS-001-38W",
                    "attrs": {"size": "38", "color": "White"},
                    "stock": 15,
                },
                {
                    "name": "39 / White",
                    "sku": "WMN-RNS-001-39W",
                    "attrs": {"size": "39", "color": "White"},
                    "stock": 20,
                },
                {
                    "name": "40 / White",
                    "sku": "WMN-RNS-001-40W",
                    "attrs": {"size": "40", "color": "White"},
                    "stock": 15,
                },
                {
                    "name": "39 / Black",
                    "sku": "WMN-RNS-001-39B",
                    "attrs": {"size": "39", "color": "Black"},
                    "stock": 15,
                },
            ],
        },
        # ── Books ──
        {
            "name": "Python Programming Guide",
            "slug": "python-programming-guide",
            "sku": "BOOK-PY-001",
            "price": Decimal("34.99"),
            "cat": "books",
            "weight": Decimal("0.60"),
            "desc": "Comprehensive guide from basics to advanced Python.",
        },
        {
            "name": "JavaScript: The Good Parts",
            "slug": "js-good-parts",
            "sku": "BOOK-JS-001",
            "price": Decimal("29.99"),
            "cat": "books",
            "weight": Decimal("0.40"),
            "desc": "Classic guide to the elegant parts of JavaScript.",
        },
        {
            "name": "Clean Code",
            "slug": "clean-code",
            "sku": "BOOK-CC-001",
            "price": Decimal("39.99"),
            "cat": "books",
            "weight": Decimal("0.55"),
            "desc": "A handbook of agile software craftsmanship.",
        },
        {
            "name": "Design Patterns",
            "slug": "design-patterns",
            "sku": "BOOK-DP-001",
            "price": Decimal("44.99"),
            "cat": "books",
            "weight": Decimal("0.70"),
            "desc": "Elements of reusable object-oriented software.",
        },
        {
            "name": "E-Book: Clean Code (Digital)",
            "slug": "ebook-clean-code",
            "sku": "BOOK-CC-DIG",
            "price": Decimal("19.99"),
            "cat": "books",
            "desc": "Digital edition of Clean Code.",
            "is_digital": True,
        },
        {
            "name": "E-Book: Python Cookbook",
            "slug": "ebook-python-cookbook",
            "sku": "BOOK-PYC-DIG",
            "price": Decimal("24.99"),
            "cat": "books",
            "desc": "Recipes for mastering Python 3.",
            "is_digital": True,
        },
        {
            "name": "E-Book: Vue.js in Action",
            "slug": "ebook-vuejs-action",
            "sku": "BOOK-VUE-DIG",
            "price": Decimal("22.99"),
            "cat": "books",
            "desc": "Build reactive web apps with Vue 3.",
            "is_digital": True,
        },
        # ── Home & Garden ──
        {
            "name": "Desk Lamp LED",
            "slug": "desk-lamp-led",
            "sku": "HOME-DLL-001",
            "price": Decimal("29.99"),
            "cat": "home-garden",
            "weight": Decimal("0.80"),
            "desc": "Adjustable arm, 5 brightness levels, USB charging port.",
            "stock": 70,
        },
        {
            "name": "Indoor Plant Pot Set",
            "slug": "plant-pot-set",
            "sku": "HOME-PPS-001",
            "price": Decimal("24.99"),
            "cat": "home-garden",
            "weight": Decimal("1.20"),
            "desc": "Set of 3 ceramic pots with drainage holes.",
            "variants": [
                {
                    "name": "White Set",
                    "sku": "HOME-PPS-001-WHT",
                    "attrs": {"color": "White"},
                    "stock": 30,
                },
                {
                    "name": "Terracotta Set",
                    "sku": "HOME-PPS-001-TRC",
                    "attrs": {"color": "Terracotta"},
                    "stock": 25,
                },
            ],
        },
        {
            "name": "Bamboo Cutting Board",
            "slug": "bamboo-cutting-board",
            "sku": "HOME-BCB-001",
            "price": Decimal("18.99"),
            "cat": "home-garden",
            "weight": Decimal("0.90"),
            "desc": "Large organic bamboo board with juice groove.",
            "stock": 85,
        },
        {
            "name": "Scented Candle Set",
            "slug": "scented-candle-set",
            "sku": "HOME-SCS-001",
            "price": Decimal("22.99"),
            "cat": "home-garden",
            "weight": Decimal("0.60"),
            "desc": "Set of 4 soy wax candles: lavender, vanilla, cedar, citrus.",
            "stock": 55,
        },
        {
            "name": "Garden Tool Set 5pc",
            "slug": "garden-tool-set",
            "sku": "HOME-GTS-001",
            "price": Decimal("34.99"),
            "cat": "home-garden",
            "weight": Decimal("1.80"),
            "desc": "Trowel, fork, pruner, weeder, gloves in carry bag.",
            "stock": 40,
        },
        {
            "name": "Throw Pillow Cover",
            "slug": "throw-pillow-cover",
            "sku": "HOME-TPC-001",
            "price": Decimal("14.99"),
            "cat": "home-garden",
            "weight": Decimal("0.15"),
            "desc": "Linen blend, 45x45cm, hidden zipper.",
            "variants": [
                {
                    "name": "Beige",
                    "sku": "HOME-TPC-001-BEI",
                    "attrs": {"color": "Beige"},
                    "stock": 45,
                },
                {
                    "name": "Sage Green",
                    "sku": "HOME-TPC-001-SGR",
                    "attrs": {"color": "Sage Green"},
                    "stock": 35,
                },
                {
                    "name": "Dusty Rose",
                    "sku": "HOME-TPC-001-DRS",
                    "attrs": {"color": "Dusty Rose"},
                    "stock": 30,
                },
            ],
        },
        {
            "name": "Wall Clock Minimalist",
            "slug": "wall-clock-minimalist",
            "sku": "HOME-WCM-001",
            "price": Decimal("27.99"),
            "cat": "home-garden",
            "weight": Decimal("0.50"),
            "desc": "30cm diameter, silent sweep movement.",
            "stock": 45,
        },
        {
            "name": "Cotton Throw Blanket",
            "slug": "cotton-throw-blanket",
            "sku": "HOME-CTB-001",
            "price": Decimal("39.99"),
            "cat": "home-garden",
            "weight": Decimal("0.90"),
            "desc": "Waffle weave, 150x200cm, machine washable.",
            "stock": 30,
        },
        {
            "name": "Stainless Steel Water Bottle",
            "slug": "water-bottle-steel",
            "sku": "HOME-SWB-001",
            "price": Decimal("16.99"),
            "cat": "home-garden",
            "weight": Decimal("0.30"),
            "desc": "750ml, double-wall insulated, keeps cold 24h.",
            "stock": 120,
        },
        {
            "name": "Ceramic Coffee Mug Set",
            "slug": "coffee-mug-set",
            "sku": "HOME-CMS-001",
            "price": Decimal("19.99"),
            "cat": "home-garden",
            "weight": Decimal("0.80"),
            "desc": "Set of 4, 350ml each, microwave safe.",
            "stock": 65,
        },
    ]


def _populate_cms_content(session):
    """Create CMS layouts, widgets, and pages for the shop storefront."""
    try:
        from plugins.cms.src.models.cms_layout import CmsLayout
        from plugins.cms.src.models.cms_widget import CmsWidget
        from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
        from plugins.cms.src.models.cms_post import CmsPost
        from plugins.cms.src.models.cms_term import CmsTerm
    except ImportError:
        logger.info("[shop] CMS plugin not installed — skipping CMS content")
        return

    def _get_or_create(model, slug, **kwargs):
        obj = session.query(model).filter_by(slug=slug).first()
        if obj:
            return obj, False
        obj = model(slug=slug, **kwargs)
        session.add(obj)
        session.flush()
        return obj, True

    def _assign_widget(layout, widget, area_name, sort_order=0):
        exists = (
            session.query(CmsLayoutWidget)
            .filter_by(layout_id=layout.id, widget_id=widget.id, area_name=area_name)
            .first()
        )
        if not exists:
            session.add(
                CmsLayoutWidget(
                    layout_id=layout.id,
                    widget_id=widget.id,
                    area_name=area_name,
                    sort_order=sort_order,
                )
            )
            session.flush()

    # CMS Category
    cms_cat, created = _get_or_create(
        CmsTerm, "shop", term_type="category", name="Shop", sort_order=70
    )
    if created:
        logger.info("[shop] Created CMS category: shop")

    # Layouts
    layout_catalogue, created = _get_or_create(
        CmsLayout,
        "shop-catalogue",
        name="Shop Catalogue",
        description="Product catalogue with category navigation and grid",
        areas=[
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "breadcrumbs", "type": "vue", "label": ""},
            {"name": "category-nav", "type": "vue", "label": "Category Navigation"},
            {"name": "product-grid", "type": "vue", "label": "Product Grid"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        sort_order=30,
        is_active=True,
    )
    if created:
        logger.info("[shop] Created CMS layout: shop-catalogue")

    layout_detail, created = _get_or_create(
        CmsLayout,
        "shop-product-detail",
        name="Product Detail",
        description="Single product page with gallery and add to cart",
        areas=[
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "breadcrumbs", "type": "vue", "label": ""},
            {"name": "product-detail", "type": "vue", "label": "Product Detail"},
            {"name": "product-carousel", "type": "vue", "label": "Related Products"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        sort_order=31,
        is_active=True,
    )
    if created:
        logger.info("[shop] Created CMS layout: shop-product-detail")

    layout_cart, created = _get_or_create(
        CmsLayout,
        "shop-cart",
        name="Shopping Cart",
        description="Shopping cart page",
        areas=[
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "breadcrumbs", "type": "vue", "label": ""},
            {"name": "cart", "type": "vue", "label": "Shopping Cart"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        sort_order=32,
        is_active=True,
    )
    if created:
        logger.info("[shop] Created CMS layout: shop-cart")

    # Widgets
    widget_grid, _ = _get_or_create(
        CmsWidget,
        "product-grid",
        name="Product Grid",
        widget_type="vue-component",
        content_json={"component": "ProductGrid", "items_per_page": 12},
        is_active=True,
    )
    widget_product_detail, _ = _get_or_create(
        CmsWidget,
        "product-detail",
        name="Product Detail",
        widget_type="vue-component",
        content_json={"component": "ProductDetail"},
        is_active=True,
    )
    widget_carousel, _ = _get_or_create(
        CmsWidget,
        "product-carousel",
        name="Product Carousel",
        widget_type="vue-component",
        content_json={"component": "ProductCarousel", "max_items": 8},
        is_active=True,
    )
    widget_category_nav, _ = _get_or_create(
        CmsWidget,
        "category-nav",
        name="Category Navigation",
        widget_type="vue-component",
        content_json={"component": "CategoryNav"},
        is_active=True,
    )
    widget_shopping_cart, _ = _get_or_create(
        CmsWidget,
        "shopping-cart",
        name="Shopping Cart",
        widget_type="vue-component",
        content_json={"component": "ShoppingCart"},
        is_active=True,
    )
    _get_or_create(
        CmsWidget,
        "cart-badge",
        name="Cart Badge",
        widget_type="vue-component",
        content_json={"component": "CartBadge"},
        is_active=True,
    )

    # Plugin-specific content widgets
    _assign_widget(layout_catalogue, widget_category_nav, "category-nav", 0)
    _assign_widget(layout_catalogue, widget_grid, "product-grid", 0)
    _assign_widget(layout_detail, widget_product_detail, "product-detail", 0)
    _assign_widget(layout_detail, widget_carousel, "product-carousel", 0)
    _assign_widget(layout_cart, widget_shopping_cart, "cart", 0)

    # Pages
    _get_or_create(
        CmsPost,
        "shop",
        type="page",
        title="Shop",
        language="en",
        content_json={"type": "doc", "content": []},
        status="published",
        layout_id=layout_catalogue.id,
        meta_title="Shop",
        meta_description="Browse our products — electronics, clothing, books and more",
        robots="index,follow",
    )
    _get_or_create(
        CmsPost,
        "shop-product-detail",
        type="page",
        title="Product Detail",
        language="en",
        content_json={"type": "doc", "content": []},
        status="published",
        layout_id=layout_detail.id,
        meta_title="Product",
        meta_description="Product details",
        robots="index,follow",
    )
    _get_or_create(
        CmsPost,
        "shop-cart",
        type="page",
        title="Shopping Cart",
        language="en",
        content_json={"type": "doc", "content": []},
        status="published",
        layout_id=layout_cart.id,
        meta_title="Shopping Cart",
        meta_description="Review your cart and proceed to checkout",
        robots="noindex,follow",
    )

    # ── Checkout Success Layout + Page (shared by every billing-completing plugin) ──
    from plugins.checkout.populate_db import populate_checkout_cms

    populate_checkout_cms()
    layout_checkout_confirm = (
        session.query(CmsLayout).filter_by(slug="checkout-confirmation").first()
    )

    # Shared navigation widgets (header + breadcrumbs + footer) for all shop layouts
    header_nav = session.query(CmsWidget).filter_by(slug="header-nav").first()
    footer_nav = session.query(CmsWidget).filter_by(slug="footer-nav").first()
    breadcrumbs_widget = session.query(CmsWidget).filter_by(slug="breadcrumbs").first()

    layouts_for_nav = [layout_catalogue, layout_detail, layout_cart]
    if layout_checkout_confirm:
        layouts_for_nav.append(layout_checkout_confirm)
    for layout in layouts_for_nav:
        if header_nav:
            _assign_widget(layout, header_nav, "header", 0)
        if breadcrumbs_widget:
            _assign_widget(layout, breadcrumbs_widget, "breadcrumbs", 0)
        if footer_nav:
            _assign_widget(layout, footer_nav, "footer", 0)

    # Add "Shop" to header-nav menu + enable cart icon
    header_nav = session.query(CmsWidget).filter_by(slug="header-nav").first()
    if header_nav:
        # Enable cart icon
        current_config = header_nav.config or {}
        if not current_config.get("show_cart"):
            header_nav.config = {**current_config, "show_cart": True}
            logger.info("[shop] Enabled show_cart on header-nav widget")

        # Add "Shop" menu item if not exists
        try:
            from plugins.cms.src.models.cms_menu_item import CmsMenuItem

            shop_exists = (
                session.query(CmsMenuItem)
                .filter_by(widget_id=header_nav.id, page_slug="shop")
                .first()
            )
            if not shop_exists:
                existing_count = (
                    session.query(CmsMenuItem)
                    .filter_by(widget_id=header_nav.id)
                    .count()
                )
                shop_menu_item = CmsMenuItem(
                    id=uuid4(),
                    widget_id=header_nav.id,
                    label="Shop",
                    page_slug="shop",
                    sort_order=existing_count,
                )
                session.add(shop_menu_item)
                logger.info("[shop] Added 'Shop' to header-nav menu")
        except ImportError:
            pass

    session.commit()
    logger.info("[shop] CMS content populated")


def _populate_email_templates(session):
    """Import shop email templates."""
    import json
    import os

    templates_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "docs",
        "imports",
        "email",
        "shop-email-templates.json",
    )

    if not os.path.exists(templates_path):
        logger.info("[shop] Email templates file not found — skipping")
        return

    try:
        from plugins.email.src.models.email_template import EmailTemplate
    except ImportError:
        logger.info("[shop] Email plugin not installed — skipping templates")
        return

    with open(templates_path) as file_handle:
        templates = json.load(file_handle)

    for template_data in templates:
        existing = (
            session.query(EmailTemplate)
            .filter_by(event_type=template_data["event_type"])
            .first()
        )
        if not existing:
            template = EmailTemplate(
                id=uuid4(),
                event_type=template_data["event_type"],
                subject=template_data["subject"],
                html_body=template_data["html_body"],
                text_body=template_data["text_body"],
                is_active=template_data.get("is_active", True),
            )
            session.add(template)
            logger.info(
                "[shop] Created email template: %s",
                template_data["event_type"],
            )

    session.commit()
    logger.info("[shop] Email templates populated")
