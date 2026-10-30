# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from openupgradelib import openupgrade


def _remap_create_lead_and_forward(env):
    """The combined step was removed (odoo/odoo@895154fd1725).

    ``create_lead`` still creates the lead and assigns it. The automatic
    forward-to-operator half of the old step is not recreated: inserting a
    step would rewrite answer triggers and sequences.
    """
    if not openupgrade.column_exists(env.cr, "chatbot_script_step", "step_type"):
        return
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE chatbot_script_step
        SET step_type = 'create_lead'
        WHERE step_type = 'create_lead_and_forward'
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _remap_create_lead_and_forward(env)
