# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _prepare_sale_delay_company_dependent(env):
    """``product.template.sale_delay`` moves from stock and becomes company-dependent.

    19.0 stores one integer. 20.0 stores a jsonb object of company id to lead
    time. Rename the integer column so the ORM can create the jsonb column.
    Post-migration copies the value onto every company. ``product.product``
    has no column of its own; the field is delegated to the template.
    """
    cr = env.cr
    if openupgrade.column_exists(cr, "product_template", "sale_delay"):
        cr.execute(
            """
            SELECT data_type
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'product_template'
               AND column_name = 'sale_delay'
            """
        )
        data_type = cr.fetchone()[0]
        if data_type in ("integer", "bigint", "smallint"):
            openupgrade.rename_columns(cr, {"product_template": [("sale_delay", None)]})
    for model in ("product.template", "product.product"):
        openupgrade.update_module_moved_fields(
            cr, model, ["sale_delay"], "stock", "sale"
        )


@openupgrade.migrate()
def migrate(env, version):
    _prepare_sale_delay_company_dependent(env)
