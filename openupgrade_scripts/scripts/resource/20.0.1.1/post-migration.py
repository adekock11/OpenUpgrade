# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def _convert_two_week_attendances(cr):
    """Turn a two-week pattern into a variable calendar.

    v19 week_type follows ``floor((date.toordinal() - 1) / 7) % 2``, so a
    given weekday keeps its week type every 14 days. Each work line becomes
    one attendance dated on a matching weekday, repeating every 2 weeks
    forever. Lines with no week type applied to both weeks and repeat weekly.
    Anchor dates are Mondays of two consecutive week-type blocks (2024-01-01
    is a Monday), so each (weekday, week_type) pair occurs exactly once.
    """
    if not openupgrade.column_exists(cr, "resource_calendar_attendance", "week_type"):
        return
    openupgrade.logged_query(
        cr,
        """
        WITH anchors AS (
            SELECT
                anchor::date AS anchor_date,
                MOD((anchor::date - DATE '0001-01-01') / 7, 2) AS week_type,
                (EXTRACT(ISODOW FROM anchor::date)::int - 1)::varchar AS dayofweek
            FROM generate_series(
                DATE '2024-01-01',
                DATE '2024-01-14',
                INTERVAL '1 day'
            ) AS anchor
        )
        UPDATE resource_calendar_attendance AS attendance
        SET
            date = anchors.anchor_date,
            recurrency = TRUE,
            recurrency_type = 'weeks',
            recurrency_interval = CASE
                WHEN attendance.week_type IS NULL THEN 1
                ELSE 2
            END,
            recurrency_end_type = 'forever',
            recurrency_until = DATE '9999-12-31',
            dayofweek = anchors.dayofweek
        FROM resource_calendar AS calendar, anchors
        WHERE attendance.calendar_id = calendar.id
          AND calendar.calendar_type = 'variable'
          AND attendance.date IS NULL
          AND anchors.dayofweek = attendance.dayofweek
          AND (
              (attendance.week_type IS NULL AND anchors.week_type = 0)
              OR attendance.week_type = anchors.week_type::varchar
          )
        """,
    )


def _drop_undefined_attendances(cr):
    """Undefined calendars have no slots. v19 ignored attendances while the
    calendar was flexible; the v20 cleanup cron would delete them anyway.
    """
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM resource_calendar_attendance AS attendance
        USING resource_calendar AS calendar
        WHERE attendance.calendar_id = calendar.id
          AND calendar.calendar_type = 'undefined'
        """,
    )


def _warn_calendar_timezones(cr):
    """Per-calendar tz is gone. Resource tz is unchanged; company tz is what
    calendar-level math uses now. Log calendars that will not match.
    """
    if not openupgrade.column_exists(cr, "resource_calendar", "tz"):
        return
    cr.execute(
        """
        SELECT calendar.id, calendar.name, calendar.tz, company.tz
        FROM resource_calendar AS calendar
        JOIN res_company AS company ON company.id = calendar.company_id
        WHERE calendar.tz IS NOT NULL
          AND company.tz IS NOT NULL
          AND calendar.tz <> company.tz
        """
    )
    rows = cr.fetchall()
    if not rows:
        return
    _logger.warning(
        "resource: %s calendar(s) had a timezone different from their company. "
        "v20 keeps a single timezone on the company (and on each resource). "
        "Examples: %s",
        len(rows),
        rows[:10],
    )


@openupgrade.migrate()
def migrate(env, version):
    _convert_two_week_attendances(env.cr)
    _drop_undefined_attendances(env.cr)
    _warn_calendar_timezones(env.cr)
    openupgrade.load_data(env, "resource", "20.0.1.1/noupdate_changes.xml")
