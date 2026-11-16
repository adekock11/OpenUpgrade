# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _delete_accrued_revenue_action(env):
    """The accrued-revenue action changes model from ``ir.actions.act_window``
    to ``ir.actions.server``.

    19.0 ``sale.action_accrued_revenue_entry_sale_order_line`` is a window on
    ``account.accrued.orders.wizard``, bound to ``sale.order.line``. 20.0 is a
    server action on ``sale.order.line`` whose code calls
    ``records.action_open_accrual_wizard()``. Leaving the window in place
    makes the data file raise ``ParseError`` (record of a different model).
    """
    openupgrade.delete_records_safely_by_xml_id(
        env,
        ["sale.action_accrued_revenue_entry_sale_order_line"],
    )


@openupgrade.migrate()
def migrate(env, version):
    _delete_accrued_revenue_action(env)
