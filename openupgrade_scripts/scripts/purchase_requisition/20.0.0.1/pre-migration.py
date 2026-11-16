# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

_UOM_RENAMES = [
    (
        "purchase.requisition.line",
        "purchase_requisition_line",
        "product_uom_id",
        "uom_id",
    ),
]


def _rename_uom_fields(env):
    """``purchase.requisition.line.product_uom_id`` was renamed to ``uom_id``."""
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
    _rename_uom_fields(env)
