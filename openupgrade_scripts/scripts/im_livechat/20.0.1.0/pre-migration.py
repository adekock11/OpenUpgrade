# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Preserve chatbot.script source_id for the crm_livechat migration.

im_livechat is updated before crm_livechat and drops source_id (the model
no longer inherits utm.source.mixin). crm_livechat post-migration reads
``ou_crm_livechat_chatbot_source`` to set crm.lead.utm_reference.

This file does not migrate the rest of im_livechat. That module needs its
own PR (conversation tags, ratings, livechat_operator_id, ...). Merge this
function into that pre-migration if both land.
"""

import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def _preserve_chatbot_script_source(env):
    cr = env.cr
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", ("crm_livechat",))
    row = cr.fetchone()
    if not row or row[0] not in ("installed", "to upgrade", "to install"):
        return
    if not openupgrade.column_exists(cr, "chatbot_script", "source_id"):
        return
    openupgrade.logged_query(
        cr,
        """
        CREATE TABLE IF NOT EXISTS ou_crm_livechat_chatbot_source (
            chatbot_script_id integer PRIMARY KEY,
            source_id integer NOT NULL
        )
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        INSERT INTO ou_crm_livechat_chatbot_source (chatbot_script_id, source_id)
        SELECT id, source_id
        FROM chatbot_script
        WHERE source_id IS NOT NULL
        ON CONFLICT (chatbot_script_id) DO NOTHING
        """,
    )
    _logger.info(
        "Saved %s chatbot.script source links for crm_livechat.",
        cr.rowcount,
    )


@openupgrade.migrate()
def migrate(env, version):
    _preserve_chatbot_script_source(env)
