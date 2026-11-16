# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _fill_sale_delay_company_dependent(env):
    """Copy the legacy integer lead time into the company-dependent jsonb column.

    The same value is stored for every company: 19.0 had one delay per product.
    A null legacy value is left empty so the field default applies.
    """
    legacy = openupgrade.get_legacy_name("sale_delay")
    cr = env.cr
    if not openupgrade.column_exists(cr, "product_template", legacy):
        return
    if not openupgrade.column_exists(cr, "product_template", "sale_delay"):
        return
    openupgrade.logged_query(
        cr,
        f"""
        UPDATE product_template AS template
           SET sale_delay = values_by_company.sale_delay
          FROM (
                SELECT template2.id,
                       jsonb_object_agg(company.id::text, template2.{legacy})
                           AS sale_delay
                  FROM product_template AS template2
                  JOIN res_company AS company ON TRUE
                 WHERE template2.{legacy} IS NOT NULL
                 GROUP BY template2.id
               ) AS values_by_company
         WHERE template.id = values_by_company.id
           AND (
                template.sale_delay IS NULL
                OR template.sale_delay = '{{}}'::jsonb
               )
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _fill_sale_delay_company_dependent(env)
