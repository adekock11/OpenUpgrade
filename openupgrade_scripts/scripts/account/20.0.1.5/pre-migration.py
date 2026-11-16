# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def _fill_tax_repartition_document_type(cr):
    """``account.tax.repartition.line.document_type`` is required.

    The column has existed since the tax repartition model was introduced, and
    the 20.0 analysis does not change it. Databases that started before Odoo 16
    can still have NULL rows from the original addition of the column, and
    Odoo then reports ``Missing not-null constraint on
    account.tax.repartition.line.document_type`` instead of setting NOT NULL.

    A line used only on refund moves becomes ``refund``. Any other line,
    including lines that are unused or used on both invoices and refunds,
    becomes ``invoice`` (the repartition Odoo creates first).
    """
    if not openupgrade.column_exists(
        cr, "account_tax_repartition_line", "document_type"
    ):
        return
    if openupgrade.column_exists(
        cr, "account_move_line", "tax_repartition_line_id"
    ) and openupgrade.column_exists(cr, "account_move", "move_type"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE account_tax_repartition_line AS line
               SET document_type = usage.document_type
              FROM (
                    SELECT aml.tax_repartition_line_id,
                           CASE
                               WHEN bool_or(
                                       am.move_type IN ('out_refund', 'in_refund')
                                   )
                                AND NOT bool_or(
                                        am.move_type IN (
                                            'out_invoice', 'in_invoice',
                                            'out_receipt', 'in_receipt'
                                        )
                                    )
                               THEN 'refund'
                               ELSE 'invoice'
                           END AS document_type
                      FROM account_move_line AS aml
                      JOIN account_move AS am
                        ON am.id = aml.move_id
                     WHERE aml.tax_repartition_line_id IS NOT NULL
                     GROUP BY aml.tax_repartition_line_id
                   ) AS usage
             WHERE line.id = usage.tax_repartition_line_id
               AND line.document_type IS NULL
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE account_tax_repartition_line
           SET document_type = 'invoice'
         WHERE document_type IS NULL
        """,
    )
    cr.execute(
        """
        SELECT COUNT(*)
          FROM account_tax_repartition_line
         WHERE document_type IS NULL
            OR document_type NOT IN ('invoice', 'refund')
        """
    )
    remaining = cr.fetchone()[0]
    if remaining:
        _logger.warning(
            "%s tax repartition lines still have no invoice/refund document_type.",
            remaining,
        )


# Fields whose ir.model.fields xmlid moved from stock_account to account.
# upgrade_analysis: "module is now 'account' ('stock_account')".
_STOCK_ACCOUNT_FIELDS_MOVED_TO_ACCOUNT = (
    (
        "account.account",
        ["account_stock_expense_id", "account_stock_variation_id"],
    ),
    ("account.move.line", ["cogs_origin_id"]),
    (
        "product.category",
        [
            "account_stock_variation_id",
            "property_cost_method",
            "property_price_difference_account_id",
            "property_stock_journal",
            "property_stock_valuation_account_id",
            "property_valuation",
        ],
    ),
    ("product.product", ["cost_method", "valuation"]),
    ("product.template", ["cost_method", "valuation"]),
    (
        "res.company",
        [
            "account_stock_journal_id",
            "account_stock_valuation_id",
            "cost_method",
            "inventory_period",
            "inventory_valuation",
        ],
    ),
)

_STOCK_ACCOUNT_RENAMED_XMLIDS = [
    (
        "stock_account.action_report_stock_valuation",
        "account.action_report_stock_valuation",
    ),
    (
        "stock_account.ir_cron_post_stock_valuation",
        "account.ir_cron_post_stock_valuation",
    ),
]


def _move_stock_account_records(env):
    """Adopt stock_account records and fields that now belong to account.

    ``account.action_report_stock_valuation`` still uses the path
    ``stock-valuation-closing``. Account is loaded before stock_account, so the
    rename has to happen here: otherwise account's data file inserts a second
    client action and PostgreSQL raises ir_act_client_path_unique.
    """
    openupgrade.rename_xmlids(env.cr, _STOCK_ACCOUNT_RENAMED_XMLIDS)
    for model, field_names in _STOCK_ACCOUNT_FIELDS_MOVED_TO_ACCOUNT:
        openupgrade.update_module_moved_fields(
            env.cr, model, field_names, "stock_account", "account"
        )


@openupgrade.migrate()
def migrate(env, version):
    _fill_tax_repartition_document_type(env.cr)
    _move_stock_account_records(env)
