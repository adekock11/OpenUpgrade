# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def _preserve_chatbot_script_source(env):
    """Preserve chatbot.script source_id for the crm_livechat migration.

    Copied from adekock11/OpenUpgrade#2 (cursor/crm-190-200-91bd). im_livechat
    is updated before crm_livechat and drops source_id (the model no longer
    inherits utm.source.mixin). crm_livechat post-migration reads
    ``ou_crm_livechat_chatbot_source`` to set crm.lead.utm_reference.
    """
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


def _migrate_livechat_ratings(cr):
    """Ratings moved off ``rating.mixin`` onto ``discuss.channel.livechat_rating``.

    19.0 stored the last rating as a float (1, 3 or 5) in ``rating_last_value``.
    20.0 stores the same scale as a selection. ``im_livechat.channel.member.history``
    no longer points at ``rating.rating``; its stored ``rating`` is recomputed
    from ``livechat_rating`` when the module initializes. ``rating.rating``
    rows themselves are left in place.
    """
    if not openupgrade.column_exists(cr, "discuss_channel", "rating_last_value"):
        return
    if not openupgrade.column_exists(cr, "discuss_channel", "livechat_rating"):
        openupgrade.logged_query(
            cr,
            "ALTER TABLE discuss_channel ADD COLUMN livechat_rating varchar",
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel
           SET livechat_rating = CASE round(rating_last_value)
                    WHEN 1 THEN '1'
                    WHEN 3 THEN '3'
                    WHEN 5 THEN '5'
               END
         WHERE channel_type = 'livechat'
           AND rating_last_value IS NOT NULL
           AND round(rating_last_value) IN (1, 3, 5)
           AND livechat_rating IS NULL
        """,
    )


def _map_waiting_status(cr):
    """The ``waiting`` livechat status ("Waiting for customer") was removed.

    An open session becomes ``in_progress``. A closed session must have an
    empty status (``livechat_end_dt`` / ``livechat_status`` check).
    """
    if not openupgrade.column_exists(cr, "discuss_channel", "livechat_status"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel
           SET livechat_status = CASE
                    WHEN livechat_end_dt IS NOT NULL THEN NULL
                    ELSE 'in_progress'
               END
         WHERE livechat_status = 'waiting'
        """,
    )


def _prepare_looking_for_help_date(cr):
    """The new check requires a timestamp exactly when status is ``need_help``.

    Fill it before the constraint is added. The stored compute overwrites the
    value with "now" during init, which is the same information 19.0 kept
    (the field did not exist, so the original request time is unknown).
    """
    if not openupgrade.column_exists(cr, "discuss_channel", "livechat_status"):
        return
    if not openupgrade.column_exists(
        cr, "discuss_channel", "livechat_looking_for_help_since_dt"
    ):
        openupgrade.logged_query(
            cr,
            """
            ALTER TABLE discuss_channel
                ADD COLUMN livechat_looking_for_help_since_dt timestamp
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel
           SET livechat_looking_for_help_since_dt = (now() AT TIME ZONE 'UTC')
         WHERE livechat_status = 'need_help'
           AND livechat_looking_for_help_since_dt IS NULL
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    # Must run before the column is dropped, and before the rating/status
    # updates. Same SQL as OpenUpgrade PR #2.
    _preserve_chatbot_script_source(env)
    _migrate_livechat_ratings(env.cr)
    _map_waiting_status(env.cr)
    _prepare_looking_for_help_date(env.cr)
