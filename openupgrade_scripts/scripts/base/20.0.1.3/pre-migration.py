# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

# pylint: disable=odoo-addons-relative-import
from odoo.addons.openupgrade_scripts.apriori import removed_modules


def _remove_obsolete_modules(env):
    """Mark modules that disappeared from the distribution as ``to remove``.

    Odoo logs ``module <name>: manifest not found`` from ``button_upgrade``
    (that runs before migration scripts) and would leave the row ``to upgrade``.
    ``base`` pre-migration moves the modules listed in ``apriori.removed_modules``
    to ``to remove``. The end of the upgrade then calls ``module_uninstall``,
    which deletes the module's views and assets and sets the state to
    ``uninstalled``. ``theme_common`` (design-themes) is the 20.0 case: the
    snippets library was removed and was not merged into ``website``.
    """
    if not removed_modules:
        return
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE ir_module_module
           SET state = 'to remove'
         WHERE name IN %s
           AND state IN ('installed', 'to upgrade', 'to install')
        """,
        (tuple(removed_modules),),
    )


def ir_actions_server_update_property(env):
    """Pre-create ``ir.actions.server.update_property``.

    The field is a stored computed char. Its compute
    (``_compute_crud_relations`` / ``_get_relation_chain``) does
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
    _remove_obsolete_modules(env)
    ir_actions_server_update_property(env)
