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


@openupgrade.migrate()
def migrate(env, version):
    _fill_tax_repartition_document_type(env.cr)
