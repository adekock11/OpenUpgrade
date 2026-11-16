# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

_UOM_RENAMES = [
    ("product.supplierinfo", "product_supplierinfo", "product_uom_id", "uom_id"),
]


def _drop_category_name_trigram_indexes(env):
    """``product.category.name`` becomes a translatable jsonb column.

    gin_trgm_ops indexes on the varchar column block that conversion
    (``operator class "gin_trgm_ops" does not accept data type jsonb``).
    Drop both the current ``product_category__name_index`` and the older
    ``product_category_name_index``. Odoo recreates the trigram index.
    """
    openupgrade.logged_query(
        env.cr,
        """
        DROP INDEX IF EXISTS
            product_category_name_index,
            product_category__name_index
        """,
    )


def _rename_uom_fields(env):
    """``product.supplierinfo.product_uom_id`` was renamed to ``uom_id``."""
    renames = []
    for model, table, old, new in _UOM_RENAMES:
        if not openupgrade.column_exists(env.cr, table, old):
            continue
        if openupgrade.column_exists(env.cr, table, new):
            continue
        renames.append((model, table, old, new))
    if not renames:
        return
    openupgrade.rename_columns(
        env.cr, {table: [(old, new)] for _model, table, old, new in renames}
    )
    openupgrade.rename_fields(env, renames)


@openupgrade.migrate()
def migrate(env, version):
    _drop_category_name_trigram_indexes(env)
    _rename_uom_fields(env)
