# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    # noupdate onboarding qweb: image width and a named wrapper around the
    # shortcut section. Arch text is otherwise unchanged.
    openupgrade.load_data(env, "project_todo", "20.0.1.0/noupdate_changes.xml")
