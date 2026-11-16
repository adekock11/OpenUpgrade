# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

_UOM_RENAMES = [
    ("mrp.bom", "mrp_bom", "product_uom_id", "uom_id"),
    ("mrp.bom.byproduct", "mrp_bom_byproduct", "product_uom_id", "uom_id"),
    ("mrp.bom.line", "mrp_bom_line", "product_uom_id", "uom_id"),
    ("mrp.production", "mrp_production", "product_uom_id", "uom_id"),
    ("mrp.unbuild", "mrp_unbuild", "product_uom_id", "uom_id"),
    ("mrp.workcenter.capacity", "mrp_workcenter_capacity", "product_uom_id", "uom_id"),
]


def _rename_uom_fields(env):
    """``product_uom_id`` was renamed to ``uom_id``.

    Rename the column before the module loads, so Odoo does not add an empty
    ``uom_id`` and leave the unit on the old column. Skipped when mrp is not
    installed.
    """
    _rename_existing_fields(env, _UOM_RENAMES)


def _rename_existing_fields(env, field_spec):
    renames = []
    for model, table, old, new in field_spec:
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
