# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

_UOM_RENAMES = [
    ("stock.move", "stock_move", "product_uom", "uom_id"),
    ("stock.move.line", "stock_move_line", "product_uom_id", "uom_id"),
]


def _rename_uom_fields(env):
    """``product_uom`` / ``product_uom_id`` were renamed to ``uom_id``.

    ``stock.scrap`` drops ``product_uom_id`` with the model, so that column is
    not renamed. ``quantity_product_uom`` is a new stored field.
    """
    renames = []
    for model, table, old, new in _UOM_RENAMES:
        if not openupgrade.column_exists(env.cr, table, old):
            continue
        if openupgrade.column_exists(env.cr, table, new):
            continue
        renames.append((model, table, old, new))
    if not renames:
        return
    column_spec = {}
    for _model, table, old, new in renames:
        column_spec.setdefault(table, []).append((old, new))
    openupgrade.rename_columns(env.cr, column_spec)
    openupgrade.rename_fields(env, renames)


@openupgrade.migrate()
def migrate(env, version):
    _rename_uom_fields(env)
