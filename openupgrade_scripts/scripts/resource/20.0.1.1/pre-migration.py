# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _map_timezones(cr):
    """Map pytz names that zoneinfo dropped, before copying tz onto the company."""
    for table in ("resource_calendar", "resource_resource"):
        if not openupgrade.column_exists(cr, table, "tz"):
            continue
        openupgrade.logged_query(
            cr,
            f"""
            UPDATE {table}
            SET tz = CASE tz
                WHEN 'Europe/Kiev' THEN 'Europe/Kyiv'
                WHEN 'Portugal' THEN 'Europe/Lisbon'
                WHEN 'Poland' THEN 'Europe/Warsaw'
                ELSE tz
            END
            WHERE tz IN ('Europe/Kiev', 'Portugal', 'Poland')
            """,
        )


def _delete_obsolete_attendances(cr):
    """Drop lines that cannot survive the v20 checks.

    Lunch is no longer a day period (breaks are just gaps between slots) and
    section rows only existed to label the two weeks. Both have a duration of
    0, which the new ``duration_hours > 0`` constraint rejects.
    """
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM resource_calendar_attendance
        WHERE display_type = 'line_section'
           OR day_period = 'lunch'
        """,
    )
    # Pure duration lines store the length in duration_hours and leave the
    # clock hours at 0. v20 treats "both hours are 0" as duration-based and
    # then recomputes duration_hours only for the other lines, which would
    # reset these to 0 and fail the check. Materialise the v19 "centered on
    # noon" hours so the schedule is preserved as ordinary slots.
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar_attendance
        SET hour_from = GREATEST(0, 12 - duration_hours / 2.0),
            hour_to = LEAST(24, 12 + duration_hours / 2.0)
        WHERE COALESCE(hour_from, 0) = 0
          AND COALESCE(hour_to, 0) = 0
          AND duration_hours > 0
          AND duration_hours <= 24
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar_attendance
        SET duration_hours = hour_to - hour_from
        WHERE COALESCE(hour_to, 0) > COALESCE(hour_from, 0)
          AND (
              duration_hours IS NULL
              OR duration_hours <= 0
              OR duration_hours > 24
          )
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM resource_calendar_attendance
        WHERE duration_hours IS NULL
           OR duration_hours <= 0
           OR duration_hours > 24
        """,
    )


def _assign_fully_flexible_calendars(cr):
    """v19 resources with an empty calendar were fully flexible.

    v20 makes ``calendar_id`` required and would otherwise fill the blanks
    with the env company's default (fixed) calendar during schema init.
    One shared undefined calendar per company keeps the "work any time"
    behaviour without giving every such resource its own copy.
    """
    openupgrade.logged_query(
        cr,
        """
        WITH missing AS (
            SELECT DISTINCT
                resource.company_id,
                COALESCE(
                    NULLIF(partner.tz, ''),
                    'UTC'
                ) AS tz
            FROM resource_resource AS resource
            LEFT JOIN res_company AS company
                ON company.id = resource.company_id
            LEFT JOIN res_partner AS partner
                ON partner.id = company.partner_id
            WHERE resource.calendar_id IS NULL
        ),
        new_calendars AS (
            INSERT INTO resource_calendar (
                name, active, company_id, schedule_type, flexible_hours,
                hours_per_day, hours_per_week, full_time_required_hours,
                two_weeks_calendar, duration_based, tz,
                create_uid, create_date, write_uid, write_date
            )
            SELECT
                'Fully Flexible', TRUE, missing.company_id, 'flexible', TRUE,
                0, 0, 0,
                FALSE, FALSE, missing.tz,
                1, (now() AT TIME ZONE 'utc'), 1, (now() AT TIME ZONE 'utc')
            FROM missing
            RETURNING id, company_id
        )
        UPDATE resource_resource AS resource
        SET calendar_id = new_calendars.id
        FROM new_calendars
        WHERE resource.calendar_id IS NULL
          AND resource.company_id IS NOT DISTINCT FROM new_calendars.company_id
        """,
    )


def _prepare_calendar_type(cr):
    """Fill ``calendar_type`` and ``days_per_week`` before the ORM init.

    ``calendar_type`` defaults to ``fixed``. If that default were applied to
    flexible and two-week calendars, the new stored computes would rebuild
    ``hours_per_week`` / ``hours_per_day`` from attendances and drop the
    figures the user actually set. Pre-filling both columns makes the init
    skip those computes.
    """
    openupgrade.logged_query(
        cr,
        """
        ALTER TABLE resource_calendar
        ADD COLUMN IF NOT EXISTS calendar_type varchar
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar
        SET calendar_type = CASE
            WHEN schedule_type = 'flexible' OR flexible_hours IS TRUE
                THEN 'undefined'
            WHEN two_weeks_calendar IS TRUE THEN 'variable'
            ELSE 'fixed'
        END
        WHERE calendar_type IS NULL
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        ALTER TABLE resource_calendar
        ADD COLUMN IF NOT EXISTS days_per_week numeric
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar
        SET days_per_week = CASE
            WHEN COALESCE(hours_per_day, 0) > 0
                THEN hours_per_week / hours_per_day
            ELSE 0
        END
        WHERE calendar_type = 'undefined'
          AND days_per_week IS NULL
        """,
    )
    # v19 _get_days_per_week() averages the two weeks. Keep that figure so a
    # later hours_per_day recompute (hours_per_week / days_per_week) stays put.
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar AS calendar
        SET days_per_week = COALESCE(stats.days, 0)
        FROM (
            SELECT
                attendance.calendar_id,
                (
                    COUNT(DISTINCT attendance.dayofweek)
                        FILTER (WHERE attendance.week_type = '0')
                    + COUNT(DISTINCT attendance.dayofweek)
                        FILTER (WHERE attendance.week_type = '1')
                ) / 2.0 AS days
            FROM resource_calendar_attendance AS attendance
            GROUP BY attendance.calendar_id
        ) AS stats
        WHERE calendar.id = stats.calendar_id
          AND calendar.calendar_type = 'variable'
          AND calendar.days_per_week IS NULL
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar AS calendar
        SET days_per_week = COALESCE(stats.days, 0)
        FROM (
            SELECT
                attendance.calendar_id,
                COUNT(DISTINCT attendance.dayofweek) AS days
            FROM resource_calendar_attendance AS attendance
            GROUP BY attendance.calendar_id
        ) AS stats
        WHERE calendar.id = stats.calendar_id
          AND calendar.calendar_type = 'fixed'
          AND calendar.days_per_week IS NULL
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE resource_calendar
        SET days_per_week = 0
        WHERE days_per_week IS NULL
        """,
    )


def _prepare_company_tz(cr):
    """v19 company.tz was a non-stored related of partner.tz.

    v20 stores it and computes it from the country when the country has a
    single timezone, which would discard a partner timezone such as
    America/Los_Angeles. Creating the column here, already filled, stops
    that compute. Partner tz wins; the company's default calendar tz is only
    a fallback for companies whose partner has none.
    """
    openupgrade.logged_query(
        cr,
        """
        ALTER TABLE res_company
        ADD COLUMN IF NOT EXISTS tz varchar
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE res_company AS company
        SET tz = COALESCE(
            (
                SELECT NULLIF(partner.tz, '')
                FROM res_partner AS partner
                WHERE partner.id = company.partner_id
            ),
            (
                SELECT NULLIF(calendar.tz, '')
                FROM resource_calendar AS calendar
                WHERE calendar.id = company.resource_calendar_id
            ),
            'UTC'
        )
        WHERE company.tz IS NULL
        """,
    )


def _rename_time_type(env):
    """``time_type`` (leave/other) becomes ``count_as`` (absence/working_time)."""
    if not openupgrade.column_exists(env.cr, "resource_calendar_leaves", "time_type"):
        return
    openupgrade.copy_columns(
        env.cr,
        {"resource_calendar_leaves": [("time_type", None, None)]},
    )
    openupgrade.rename_fields(
        env,
        [
            (
                "resource.calendar.leaves",
                "resource_calendar_leaves",
                "time_type",
                "count_as",
            )
        ],
    )
    openupgrade.map_values(
        env.cr,
        openupgrade.get_legacy_name("time_type"),
        "count_as",
        [("leave", "absence"), ("other", "working_time")],
        table="resource_calendar_leaves",
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE resource_calendar_leaves
        SET count_as = 'absence'
        WHERE count_as IS NULL
           OR count_as NOT IN ('absence', 'working_time')
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _map_timezones(env.cr)
    _delete_obsolete_attendances(env.cr)
    _assign_fully_flexible_calendars(env.cr)
    _prepare_calendar_type(env.cr)
    _prepare_company_tz(env.cr)
    _rename_time_type(env)
