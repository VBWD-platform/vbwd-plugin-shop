"""Shop entity exchangers for the S46 data-exchange seam (S46.6).

Exposes the shop catalog + orders through the core ``EntityExchanger`` contract
so they appear on the generic Settings → Import/Export page and the per-list
controls.

Entities:

* ``shop_products`` (``Product``, natural key ``slug``) — import+export. ``slug``
  is the stable required-unique key (``sku`` is nullable, so it is exported but
  not used as the natural key).
* ``shop_orders`` (``Order``, natural key ``order_number``) — **export-only**:
  an order is created by the payment-capture flow and binds a user + invoice +
  its line items via UUID FKs / a cascade child relationship the engine owns, so
  it is not structurally importable. Per Liskov ``import_`` raises
  :class:`UnsupportedOperationError`. The export redacts the customer
  shipping/billing address PII unless the caller holds the PII permission.

Design notes:

* **Reused perms** — the plugin already ships ``shop.products.*`` /
  ``shop.orders.*``; each exchanger maps ``export_permission`` /
  ``import_permission`` onto those (single source of truth).
* **DRY** — products reuse :class:`BaseModelExchanger`; only the narrow
  ``_SessionModelRepository`` adapter is added (mirrors core / CMS).
* **No core change** — registration happens in ``ShopPlugin.on_enable`` through
  the shared ``db.session``; core imports no ``plugins.*`` module.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID
(one exchanger per entity, narrow ports); DI (session injected); DRY; Liskov
(orders export-only raises); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin shop --full``.
"""
from typing import Any, List, Optional

from vbwd.services.data_exchange.base_model_exchanger import (
    LOADTEST_SLUG_PREFIX,
    BaseModelExchanger,
)
from vbwd.services.data_exchange.port import (
    CLUSTER_SALES,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

# Existing shop permissions (single source — ShopPlugin.admin_permissions).
PERM_PRODUCTS_VIEW = "shop.products.view"
PERM_PRODUCTS_MANAGE = "shop.products.manage"
PERM_CATEGORIES_MANAGE = "shop.categories.manage"
PERM_ORDERS_VIEW = "shop.orders.view"

# Portable, id-free fields of a nested product variant / image row (URLs only —
# image binaries are out of scope this sprint, a later ZIP export can add them).
_VARIANT_FIELDS = (
    "name",
    "sku",
    "price",
    "price_float",
    "weight",
    "is_active",
    "sort_order",
    "attributes",
    "image_url",
)
_IMAGE_FIELDS = ("url", "alt", "sort_order", "is_primary")


class _SessionModelRepository:
    """Narrow model repo satisfying the ``BaseModelExchanger`` contract (ISP).

    Mirrors core's / CMS's adapter: the shop repositories expose paginated /
    domain finders rather than the four flat methods the base exchanger needs.
    """

    def __init__(self, session: Any, model_class: type, natural_key: str) -> None:
        self._session = session
        self._model_class = model_class
        self._natural_key = natural_key

    def find_all(self) -> List[Any]:
        return self._session.query(self._model_class).all()

    def find_by_natural_key(self, value: Any) -> Optional[Any]:
        column = getattr(self._model_class, self._natural_key)
        return self._session.query(self._model_class).filter(column == value).first()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def delete_all(self) -> None:
        self._session.query(self._model_class).delete()

    # ── heavy-load scale hooks (S89.1) ────────────────────────────────────
    # The base exchanger calls these via ``getattr`` when present so a 100k
    # seed/export is O(batches), not O(N²). Absent → it falls back to full
    # ``find_all`` scans (fine for tiny tables, too slow at load-test scale).

    def iter_rows(self, batch_size: int) -> Any:
        """Yield rows in keyset-free ``yield_per`` pages (bounded memory)."""
        return (
            self._session.query(self._model_class)
            .yield_per(batch_size)
            .enable_eagerloads(False)
        )

    def bulk_add(self, instances: List[Any]) -> None:
        """Insert a batch through the unit of work (one flush per batch).

        Uses ``add_all`` + ``flush`` rather than ``bulk_save_objects`` because
        the seeded products carry an M2M ``categories`` link that
        ``bulk_save_objects`` would silently skip (it bypasses relationship
        cascades). ``add_all`` keeps the batch a single flush — still
        O(batches), not O(N²) — while persisting the association rows. The
        caller commits the batch.
        """
        self._session.add_all(instances)
        self._session.flush()

    def find_natural_keys_with_prefix(self, prefix: str) -> List[str]:
        """Return the natural-key values that start with ``prefix`` (idempotency)."""
        column = getattr(self._model_class, self._natural_key)
        rows = self._session.query(column).filter(column.like(f"{prefix}%")).all()
        return [row[0] for row in rows]

    def delete_natural_keys_with_prefix(self, prefix: str) -> int:
        """Delete every row whose natural key starts with ``prefix``. Returns count.

        Scoped to this model and the ``loadtest-`` prefix only, so it never
        touches real/demo data. ``synchronize_session=False`` keeps the bulk
        delete a single statement (the session is committed by the caller).
        """
        column = getattr(self._model_class, self._natural_key)
        return (
            self._session.query(self._model_class)
            .filter(column.like(f"{prefix}%"))
            .delete(synchronize_session=False)
        )


class _PermissionMappedModelExchanger(BaseModelExchanger):
    """A ``BaseModelExchanger`` whose perms map onto existing shop perms."""

    def __init__(
        self,
        *,
        view_permission: str,
        manage_permission: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._view_permission = view_permission
        self._manage_permission = manage_permission

    @property
    def export_permission(self) -> str:
        return self._view_permission

    @property
    def import_permission(self) -> str:
        return self._manage_permission


class ShopProductCategoriesExchanger(_PermissionMappedModelExchanger):
    """``ProductCategory`` rows keyed by ``slug``, hierarchical via ``parent_slug``.

    ``parent_id`` is a self-referential FK; the base ``fk_natural_key_map`` would
    only serialise it on export and never resolve it on import (it would write a
    slug into the id column). So this subclass serialises the parent as
    ``parent_slug`` on export AND resolves ``parent_slug`` → local id on import,
    skipping the row with an error when the referent is absent (Liskov: never
    crash, let the caller decide).
    """

    def __init__(self, *, session: Any, **kwargs: Any) -> None:
        super().__init__(session=session, **kwargs)
        self._category_session = session

    def _serialise_row(self, row: Any, *, include_pii: bool) -> dict:
        result = super()._serialise_row(row, include_pii=include_pii)
        result.pop("parent_id", None)
        parent = getattr(row, "parent", None)
        result["parent_slug"] = parent.slug if parent is not None else None
        return result

    def _build_instance(self, row: dict) -> Any:
        attributes = {
            field_name: value
            for field_name, value in row.items()
            if field_name not in ("parent_slug",)
        }
        return self._model_class(**attributes)

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        prepared = dict(row)
        parent_slug = prepared.pop("parent_slug", None)
        if parent_slug:
            parent = self._find_category_by_slug(parent_slug)
            if parent is None:
                result.errors.append(
                    {
                        "row": index,
                        "reason": f"unknown parent category slug '{parent_slug}'",
                    }
                )
                return
            prepared["parent_id"] = parent.id
        super()._import_row(prepared, index, result, dry_run=dry_run)

    def _find_category_by_slug(self, slug: str) -> Any:
        column = getattr(self._model_class, "slug")
        return (
            self._category_session.query(self._model_class)
            .filter(column == slug)
            .first()
        )


class ShopProductsExchanger(_PermissionMappedModelExchanger):
    """``Product`` rows keyed by ``slug``, carrying their category link + children.

    The product↔category link is **M2M** (``shop_product_category_link``), so the
    serialised shape is ``category_slugs`` (a list); ``fk_natural_key_map`` cannot
    carry an M2M and never resolves on import, so the link travels here. On import
    the slugs resolve to local categories (skip-with-error when any is absent —
    Liskov). Nested ``variants`` and ``images`` (URLs only — no binaries this
    sprint) are delete-and-replaced on re-import so a round trip leaves no
    duplicate children.
    """

    # Cache of the one shared ``loadtest-`` category (S89.1 seed); ``None`` until
    # the first seeded row creates/looks it up. Declared so mypy sees the attr.
    _seed_category: Optional[Any]

    def __init__(self, *, session: Any, **kwargs: Any) -> None:
        super().__init__(session=session, **kwargs)
        self._product_session = session
        self._seed_category = None

    def _serialise_row(self, row: Any, *, include_pii: bool) -> dict:
        result = super()._serialise_row(row, include_pii=include_pii)
        result["category_slugs"] = [category.slug for category in row.categories]
        result["variants"] = [
            {field_name: getattr(variant, field_name) for field_name in _VARIANT_FIELDS}
            for variant in row.variants
        ]
        result["images"] = [
            {field_name: getattr(image, field_name) for field_name in _IMAGE_FIELDS}
            for image in row.images
        ]
        return result

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        category_slugs = row.get("category_slugs") or []
        categories = []
        for slug in category_slugs:
            category = self._find_category_by_slug(slug)
            if category is None:
                result.errors.append(
                    {"row": index, "reason": f"unknown category slug '{slug}'"}
                )
                return
            categories.append(category)

        key_value = row.get(self.natural_key)
        if not key_value:
            result.errors.append(
                {"row": index, "reason": f"missing natural key '{self.natural_key}'"}
            )
            return

        existing = self._repository.find_by_natural_key(key_value)
        scalar_row = {
            field_name: value
            for field_name, value in row.items()
            if field_name not in ("category_slugs", "variants", "images")
        }
        if existing is not None:
            if not dry_run:
                for field_name, value in scalar_row.items():
                    setattr(existing, field_name, value)
                self._apply_links(existing, categories, row)
            result.updated += 1
        else:
            if not dry_run:
                product = self._model_class(**scalar_row)
                self._repository.add(product)
                self._apply_links(product, categories, row)
            result.created += 1

    def _apply_links(self, product: Any, categories: list, row: dict) -> None:
        product.categories = list(categories)
        # Delete-and-replace children: flush the orphan deletes before inserting
        # the replacements so a re-import does not collide on a child's unique
        # ``sku`` (the old + new rows would otherwise insert in one flush).
        product.variants = []
        product.images = []
        self._product_session.flush()
        product.variants = [
            self._variant_class()(**self._child_attributes(variant, _VARIANT_FIELDS))
            for variant in (row.get("variants") or [])
        ]
        product.images = [
            self._image_class()(**self._child_attributes(image, _IMAGE_FIELDS))
            for image in (row.get("images") or [])
        ]

    def _child_attributes(self, child: dict, fields: tuple) -> dict:
        return {
            field_name: child[field_name]
            for field_name in fields
            if field_name in child
        }

    def _find_category_by_slug(self, slug: str) -> Any:
        from plugins.shop.shop.models.product_category import ProductCategory

        return (
            self._product_session.query(ProductCategory)
            .filter(ProductCategory.slug == slug)
            .first()
        )

    def _variant_class(self) -> type:
        from plugins.shop.shop.models.product_variant import ProductVariant

        return ProductVariant

    def _image_class(self) -> type:
        from plugins.shop.shop.models.product_image import ProductImage

        return ProductImage

    # ── bulk seed (S89.1) ─────────────────────────────────────────────────
    # A synthetic product needs a non-null ``name`` + ``price`` and at least one
    # category link to be a realistic, round-trippable catalog row. The base
    # ``bulk_seed`` loop builds each instance via ``_build_instance``; this
    # override returns a valid scalar row + the one shared ``loadtest-`` category
    # slug, and ``_build_instance`` attaches that category as the M2M link. The
    # tax M2M is deliberately omitted (a product is valid without an assigned
    # tax — it falls back to ``tax_class``); noted in the sprint report.

    # A fixed, valid synthetic price (currency is the global default_currency).
    _SEED_PRODUCT_PRICE = 9.99
    _SEED_CATEGORY_SLUG = f"{LOADTEST_SLUG_PREFIX}shop_products-cat"
    _SEED_CATEGORY_NAME = "Load-test products"

    def _seed_row(self, index: int, natural_value: str) -> dict:
        return {
            "slug": natural_value,
            "name": f"Load-test product {index}",
            "description": f"Synthetic load-test product {index}",
            "price": self._SEED_PRODUCT_PRICE,
            "is_active": True,
            "is_digital": False,
            "has_variants": False,
            "sort_order": index,
            "tax_class": "standard",
            "category_slugs": [self._SEED_CATEGORY_SLUG],
        }

    def _build_instance(self, row: dict) -> Any:
        """Build a ``Product`` and attach the shared load-test category (seed path).

        ``bulk_seed`` is the only caller of ``_build_instance`` for products
        (import builds the product inline in ``_import_row``); the
        ``category_slugs`` presence still gates the attach, so this stays
        seed-only and would never spawn the load-test category on any other path.
        """
        if "category_slugs" not in row:
            return super()._build_instance(row)
        prepared = dict(row)
        prepared.pop("category_slugs", None)
        product = self._model_class(**prepared)
        product.categories = [self._ensure_seed_prerequisite()]
        return product

    def _ensure_seed_prerequisite(self) -> Any:
        """Return the one shared ``loadtest-`` ``ProductCategory``, creating it once.

        Created + committed through the existing ``ProductCategoryRepository``
        (no raw SQL) and cached on the exchanger so 100k products share one
        category and a single lookup. Idempotent: an existing category (this
        run or a prior seed) is reused, never duplicated.
        """
        if self._seed_category is not None:
            return self._seed_category
        from plugins.shop.shop.models.product_category import ProductCategory
        from plugins.shop.shop.repositories.product_category_repository import (
            ProductCategoryRepository,
        )

        repository = ProductCategoryRepository(self._product_session)
        category = repository.find_by_slug(self._SEED_CATEGORY_SLUG)
        if category is None:
            category = ProductCategory(
                slug=self._SEED_CATEGORY_SLUG,
                name=self._SEED_CATEGORY_NAME,
                description="Shared category for load-test products (S89.1).",
            )
            repository.save(category)
        self._seed_category = category
        return category

    def _reset_loadtest_rows(self) -> int:
        """Drop the load-test products, then the shared category if now orphaned.

        Never touches a non-``loadtest-`` category. The cached prerequisite is
        cleared so the next seed re-creates it cleanly.
        """
        deleted = super()._reset_loadtest_rows()
        self._drop_orphaned_seed_category()
        self._seed_category = None
        return deleted

    def _drop_orphaned_seed_category(self) -> None:
        from plugins.shop.shop.models.product import Product
        from plugins.shop.shop.models.product_category import ProductCategory

        category = (
            self._product_session.query(ProductCategory)
            .filter(ProductCategory.slug == self._SEED_CATEGORY_SLUG)
            .first()
        )
        if category is None:
            return
        # Query the DB for any product still in this category rather than reading
        # the (possibly stale) relationship: the prefix delete ran with
        # ``synchronize_session=False`` so the loaded collection may be stale.
        still_referenced = (
            self._product_session.query(Product.id)
            .filter(Product.categories.any(ProductCategory.id == category.id))
            .first()
        )
        if still_referenced is None:
            self._product_session.delete(category)


class ShopOrdersExchanger(EntityExchanger):
    """``Order`` records, keyed by ``order_number`` — export-only.

    An order is created by the payment-capture flow and binds a user, an invoice
    and its line items; it is not a portable catalog row, so it is export-only.
    ``import_`` raises (Liskov) rather than pretending to upsert.
    """

    entity_key = "shop_orders"
    label = "Shop Orders"
    cluster = CLUSTER_SALES
    natural_key = "order_number"
    supports_export = True
    supports_import = False
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset()
    pii_fields = frozenset({"shipping_address", "billing_address"})

    _ROW_FIELDS = (
        "order_number",
        "user_id",
        "invoice_id",
        "status",
        "shipping_address",
        "billing_address",
        "shipping_method",
        "shipping_cost",
        "tracking_number",
        "subtotal",
        "tax_amount",
        "total_amount",
        "notes",
    )

    def __init__(self, session: Any) -> None:
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        from plugins.shop.shop.models.order import Order

        rows = self._session.query(Order).all()
        if selector.ids:
            wanted = {str(value) for value in selector.ids}
            rows = [
                row
                for row in rows
                if str(row.id) in wanted
                or (row.order_number and row.order_number in wanted)
            ]
        serialised = [self._serialise(row, include_pii=include_pii) for row in rows]
        return Envelope(entity_key=self.entity_key, rows=serialised)

    def _serialise(self, row: Any, *, include_pii: bool) -> dict:
        result: dict = {}
        for field_name in self._ROW_FIELDS:
            value = getattr(row, field_name)
            if field_name == "status" and value is not None:
                value = value.value
            if field_name in self.pii_fields and not include_pii:
                value = None
            result[field_name] = value
        return result

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        raise UnsupportedOperationError(
            "shop orders are export-only: an order is owned by the payment-capture "
            "flow and cannot be imported"
        )

    @property
    def export_permission(self) -> str:
        return PERM_ORDERS_VIEW


def build_shop_exchangers(session: Any) -> List[EntityExchanger]:
    """Construct the shop exchangers bound to ``session``.

    Order matters for a full-instance import: ``shop_product_categories`` is
    listed before ``shop_products`` so the categories a product links by slug
    exist before the products import (the unified ZIP import is dependency-aware).
    """
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.product_category import ProductCategory

    return [
        ShopProductCategoriesExchanger(
            entity_key="shop_product_categories",
            label="Shop Categories",
            cluster=CLUSTER_SALES,
            natural_key="slug",
            model_class=ProductCategory,
            repository=_SessionModelRepository(session, ProductCategory, "slug"),
            session=session,
            public_fields=[
                "slug",
                "name",
                "description",
                "image_url",
                "sort_order",
            ],
            supported_formats=frozenset({"json", "csv"}),
            view_permission=PERM_PRODUCTS_VIEW,
            manage_permission=PERM_CATEGORIES_MANAGE,
        ),
        ShopProductsExchanger(
            entity_key="shop_products",
            label="Shop Products",
            cluster=CLUSTER_SALES,
            natural_key="slug",
            model_class=Product,
            repository=_SessionModelRepository(session, Product, "slug"),
            session=session,
            public_fields=[
                "slug",
                "name",
                "description",
                "sku",
                "price",
                "is_active",
                "is_digital",
                "has_variants",
                "sort_order",
                "weight",
                "dimensions",
                "product_metadata",
                "tax_class",
            ],
            supported_formats=frozenset({"json", "csv"}),
            view_permission=PERM_PRODUCTS_VIEW,
            manage_permission=PERM_PRODUCTS_MANAGE,
        ),
        ShopOrdersExchanger(session),
    ]


def register_shop_exchangers(session: Any) -> None:
    """Register the shop exchangers into the registry (idempotent).

    Called from ``ShopPlugin.on_enable``. Re-registering replaces by key, so a
    repeat enable (per-test app) is clear-safe.
    """
    for exchanger in build_shop_exchangers(session):
        data_exchange_registry.register(exchanger)
