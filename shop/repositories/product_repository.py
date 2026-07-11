"""Product repository."""
from typing import Any, Dict, Optional, List
from uuid import UUID
from sqlalchemy import or_
from vbwd.repositories.base import BaseRepository
from vbwd.services.tags_and_custom_fields import (
    resolve_tags_and_custom_fields,
    UnknownEntityTypeError,
)
from plugins.shop.shop.models.product import Product

# The generic entity-type key shop registers (in ``on_enable``) so its products
# are taggable through the core tags port. Tag reads/filters go through that
# port only — this module never imports the tags implementation (agnostic).
_SHOP_PRODUCT_ENTITY_TYPE = "shop_product"


class ProductRepository(BaseRepository[Product]):
    def __init__(self, session):
        super().__init__(session, Product)

    def find_by_slug(self, slug: str) -> Optional[Product]:
        return self._session.query(Product).filter_by(slug=slug).first()

    def find_by_sku(self, sku: str) -> Optional[Product]:
        return self._session.query(Product).filter_by(sku=sku).first()

    def find_by_vendor_id(self, vendor_id) -> List[Product]:
        """Return the products owned by ``vendor_id`` (marketplace vendor-mode).

        Ordered by sort_order then name so the vendor's "my products" list is
        deterministic. Filtering in SQL (not Python) so a vendor never loads the
        whole catalog to see their own rows.
        """
        return (
            self._session.query(Product)
            .filter_by(vendor_id=vendor_id)
            .order_by(Product.sort_order, Product.name)
            .all()
        )

    def find_active(self, page: int = 1, per_page: int = 20) -> List[Product]:
        return (
            self._session.query(Product)
            .filter_by(is_active=True)
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def count_active(self) -> int:
        return self._session.query(Product).filter_by(is_active=True).count()

    def search(self, query: str, page: int = 1, per_page: int = 20) -> List[Product]:
        pattern = f"%{query}%"
        return (
            self._session.query(Product)
            .filter(
                Product.is_active.is_(True),
                or_(
                    Product.name.ilike(pattern),
                    Product.description.ilike(pattern),
                    Product.sku.ilike(pattern),
                ),
            )
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def find_by_category_slug(
        self, category_slug: str, page: int = 1, per_page: int = 20
    ) -> List[Product]:
        from plugins.shop.shop.models.product_category import (
            ProductCategory,
            shop_product_category_link,
        )

        return (
            self._session.query(Product)
            .join(
                shop_product_category_link,
                Product.id == shop_product_category_link.c.product_id,
            )
            .join(
                ProductCategory,
                ProductCategory.id == shop_product_category_link.c.category_id,
            )
            .filter(ProductCategory.slug == category_slug, Product.is_active.is_(True))
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def _active_query(self, query: Optional[str], category_slug: Optional[str]):
        """Active-product query with optional search + category filters applied.

        The search + category clauses are AND-composed (mirroring ghrm's
        ``find_all``) so a filtered ``total`` reflects the intersection. Tags are
        NOT filtered here — they are core-owned and resolved through the port
        (see :meth:`list_catalogue`).
        """
        active_query = self._session.query(Product).filter(Product.is_active.is_(True))
        if category_slug:
            from plugins.shop.shop.models.product_category import (
                ProductCategory,
                shop_product_category_link,
            )

            active_query = (
                active_query.join(
                    shop_product_category_link,
                    Product.id == shop_product_category_link.c.product_id,
                )
                .join(
                    ProductCategory,
                    ProductCategory.id == shop_product_category_link.c.category_id,
                )
                .filter(ProductCategory.slug == category_slug)
            )
        if query:
            pattern = f"%{query}%"
            active_query = active_query.filter(
                or_(
                    Product.name.ilike(pattern),
                    Product.description.ilike(pattern),
                    Product.sku.ilike(pattern),
                )
            )
        return active_query.order_by(Product.sort_order, Product.name)

    def list_catalogue(
        self,
        page: int = 1,
        per_page: int = 20,
        query: Optional[str] = None,
        category_slug: Optional[str] = None,
        tag_slugs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Active products for the catalogue list, with the EFFECTIVE total.

        Returns ``{"items": [Product], "total": int}`` where ``total`` counts the
        rows matching the combined search / category / tag filter (not the whole
        active catalogue), so the caller can build a correct pagination envelope.
        """
        active_query = self._active_query(query, category_slug)
        if tag_slugs:
            return self._paginate_by_tags(active_query, page, per_page, tag_slugs)
        total = active_query.count()
        items = active_query.offset((page - 1) * per_page).limit(per_page).all()
        return {"items": items, "total": total}

    def _paginate_by_tags(
        self, query, page: int, per_page: int, tag_slugs: List[str]
    ) -> Dict[str, Any]:
        """Filter the SQL candidate set by tag (AND) in Python, then paginate.

        Tags cannot be filtered in SQL without a core change (the tag rows are
        core-owned, resolved only through the port), so the SQL-filtered
        candidates are fetched unpaginated, matched against ``tag_slugs`` (a
        product matches only when it carries EVERY requested slug), and the page
        is sliced in Python. ``total`` reflects the filtered set. Mirrors ghrm.
        """
        candidates = query.all()
        tags_by_id = self.list_product_tags([product.id for product in candidates])
        required = set(tag_slugs)
        matched = [
            product
            for product in candidates
            if required.issubset(set(tags_by_id.get(product.id, [])))
        ]
        total = len(matched)
        start = (page - 1) * per_page
        return {"items": matched[start : start + per_page], "total": total}

    def list_product_tags(self, product_ids: List[UUID]) -> Dict[UUID, List[str]]:
        """Tag slugs for many products in ONE query via the core tags port.

        Degrades to an empty map when the tags port has no provider or the
        ``shop_product`` entity type is unregistered (plugin loaded without
        ``on_enable`` having run): a tag filter then yields no matches and list
        items fall back to empty tags — never a 500.
        """
        if not product_ids:
            return {}
        provider = resolve_tags_and_custom_fields()
        if provider is None:
            return {}
        try:
            return provider.get_tags_bulk(_SHOP_PRODUCT_ENTITY_TYPE, list(product_ids))
        except UnknownEntityTypeError:
            return {}

    def list_used_product_tags(self) -> List[Dict[str, Any]]:
        """Tags carried by at least one ACTIVE product (tag-filter options).

        The filter only offers tags that can actually match a product, so a
        globally-defined tag no active product carries is dropped. Degrades to
        ``[]`` when there are no active/tagged products or the port is
        unavailable — never a 500. Mirrors ghrm's ``list_package_tag_options``.
        """
        active_ids = [
            row[0]
            for row in self._session.query(Product.id)
            .filter(Product.is_active.is_(True))
            .all()
        ]
        if not active_ids:
            return []
        tags_by_id = self.list_product_tags(active_ids)
        used_slugs = {slug for slugs in tags_by_id.values() for slug in slugs}
        if not used_slugs:
            return []
        provider = resolve_tags_and_custom_fields()
        if provider is None:
            return []
        try:
            catalog = provider.list_applicable_tags(_SHOP_PRODUCT_ENTITY_TYPE)
        except UnknownEntityTypeError:
            return []
        return [tag for tag in catalog if tag.get("slug") in used_slugs]
