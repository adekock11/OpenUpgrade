# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    # Noupdate records whose definition changed. Loaded in post so base has
    # already merged ir.rule into ir.access (the sharing rule's model).
    # - mail templates gain email_layout_xmlid; body_html is not touched
    # - project_message_user_assigned: t-esc -> t-out, same sentence
    # - project_task_rule_portal_project_sharing domain uses access_mode
    openupgrade.load_data(env, "project", "20.0.1.4/noupdate_changes.xml")
