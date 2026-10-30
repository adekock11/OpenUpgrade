# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

_PRIVACY_VALUES = ("public", "private", "confidential")


def _create_missing_primary_calendars(env):
    """The post_init hook that creates primary calendars runs on install only.

    Schema init may already have created one for users who organise events
    (calendar.event.calendar_id's compute calls _find_or_create_primary_calendar).
    Everyone else who is not a portal/public user still needs one: v20 creates
    it for every new internal user and refuses to delete it.
    """
    users = (
        env["res.users"]
        .with_context(active_test=False)
        .search(
            [
                ("share", "=", False),
                ("calendar_user_ids", "not any", [("is_primary", "=", True)]),
            ]
        )
    )
    if users:
        users._generate_primary_calendar()
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE res_users AS users
        SET primary_calendar_id = membership.calendar_id
        FROM calendar_user AS membership
        WHERE membership.user_id = users.id
          AND membership.is_primary
          AND membership.access_role = 'owner'
          AND users.primary_calendar_id IS NULL
        """,
    )


def _restore_default_privacy(cr):
    """calendar_default_privacy moved from res.users.settings to the calendar.

    _generate_primary_calendar copies the system parameter (or 'public'),
    not the per-user value. The old column is still present: v20 no longer
    drops removed columns.
    """
    if not openupgrade.column_exists(
        cr, "res_users_settings", "calendar_default_privacy"
    ):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE calendar_calendar AS calendar
        SET calendar_default_privacy = settings.calendar_default_privacy
        FROM calendar_user AS membership
        JOIN res_users_settings AS settings
            ON settings.user_id = membership.user_id
        WHERE membership.calendar_id = calendar.id
          AND membership.is_primary
          AND membership.access_role = 'owner'
          AND settings.calendar_default_privacy IN %s
          AND calendar.calendar_default_privacy
              IS DISTINCT FROM settings.calendar_default_privacy
        """,
        (_PRIVACY_VALUES,),
    )


def _assign_event_calendars(cr):
    """Events belong to their organiser's primary calendar.

    The stored compute does this when it runs. Fill whatever it left empty
    (no organiser, or a calendar created only in this post script).
    """
    openupgrade.logged_query(
        cr,
        """
        UPDATE calendar_event AS event
        SET calendar_id = users.primary_calendar_id
        FROM res_users AS users
        WHERE event.user_id = users.id
          AND event.calendar_id IS NULL
          AND users.primary_calendar_id IS NOT NULL
        """,
    )


def _restore_own_filter_checked(cr):
    """The user's own events are filtered by calendar.user.is_filter_checked.

    v19 stored that checkbox on calendar.filters.partner_checked of the
    user's own partner. Other partners were folded into ``active`` in pre.
    """
    if not openupgrade.column_exists(cr, "calendar_filters", "partner_checked"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE calendar_user AS membership
        SET is_filter_checked = FALSE
        FROM res_users AS users
        JOIN calendar_filters AS filters
            ON filters.user_id = users.id
           AND filters.partner_id = users.partner_id
        WHERE membership.user_id = users.id
          AND membership.is_primary
          AND filters.partner_checked IS FALSE
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _create_missing_primary_calendars(env)
    _restore_default_privacy(env.cr)
    _assign_event_calendars(env.cr)
    _restore_own_filter_checked(env.cr)
    openupgrade.load_data(env, "calendar", "20.0.1.1/noupdate_changes.xml")
    openupgrade.delete_record_translations(
        env.cr,
        "calendar",
        [
            "calendar_template_delete_event",
            "calendar_template_meeting_changedate",
            "calendar_template_meeting_invitation",
            "calendar_template_meeting_reminder",
            "calendar_template_meeting_update",
            "subtype_invitation",
        ],
    )
