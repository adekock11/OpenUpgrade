# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _delete_mailing_list_merge_action(env):
    """The merge action changes model from ``ir.actions.act_window`` to
    ``ir.actions.server``.

    Loading ``mass_mailing/data/ir_actions_server_data.xml`` otherwise raises
    ``ParseError: For external id mass_mailing.mailing_list_merge_action when
    trying to create/update a record of model ir.actions.server found record
    of different model ir.actions.act_window``. The 19.0 window opened
    ``mailing.list.merge``. 20.0 runs ``records.action_mailing_lists_merge()``
    on ``mailing.list`` instead, so the old window is obsolete.
    """
    openupgrade.delete_records_safely_by_xml_id(
        env,
        ["mass_mailing.mailing_list_merge_action"],
    )


@openupgrade.migrate()
def migrate(env, version):
    _delete_mailing_list_merge_action(env)
