# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _ir_actions_server_update_property(env):
    """Pre-create ``ir.actions.server.update_property``.

    The field is a stored computed char. Its compute calls
    ``self.env[self.model_id.model]``. During base initialization that raises
    ``KeyError: 'helpdesk.ticket'`` (and the same for any other model that is
    not part of base) for ``object_write`` actions. NULL is the right value
    for data written before 20.0: nothing stored a property name to update.
    """
    if not openupgrade.table_exists(env.cr, "ir_act_server"):
        return
    openupgrade.add_columns(
        env,
        [
            (
                "ir.actions.server",
                "update_property",
                "char",
                None,
                "ir_act_server",
            )
        ],
    )


@openupgrade.migrate()
def migrate(env, version):
    _ir_actions_server_update_property(env)
