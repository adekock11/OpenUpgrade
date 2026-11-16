# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


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


@openupgrade.migrate()
def migrate(env, version):
    _drop_category_name_trigram_indexes(env)
