# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _merge_partner_filters(cr):
    """v20 keeps a single ``active`` flag on calendar.filters.

    v19 used ``active`` for "listed" and ``partner_checked`` for "shown".
    The shown state is what hides or displays that partner's events, so an
    unchecked filter becomes inactive. The user's own events are filtered
    through calendar.user in post-migration.
    """
    if not openupgrade.column_exists(cr, "calendar_filters", "partner_checked"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE calendar_filters
        SET active = FALSE
        WHERE partner_checked IS FALSE
          AND active IS DISTINCT FROM FALSE
        """,
    )


def _deduplicate_access_tokens(cr):
    """v20 adds UNIQUE(access_token). Several NULL tokens are allowed;
    duplicate non-null tokens are not. Keep the oldest row's token so
    existing links to that event keep working.
    """
    openupgrade.logged_query(
        cr,
        """
        UPDATE calendar_event
        SET access_token = NULL
        WHERE access_token = ''
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE calendar_event AS event
        SET access_token = gen_random_uuid()::varchar
        WHERE event.id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY access_token
                        ORDER BY id
                    ) AS occurrence
                FROM calendar_event
                WHERE access_token IS NOT NULL
            ) AS ranked
            WHERE occurrence > 1
        )
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _merge_partner_filters(env.cr)
    _deduplicate_access_tokens(env.cr)
