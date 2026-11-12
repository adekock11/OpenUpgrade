# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade
from psycopg2 import sql

_logger = logging.getLogger(__name__)

# 19.0 selection -> 20.0 hr.employee.type xmlid.
# 20.0 data (hr/data/hr_employee_type_data.xml) has no worker, contractor or
# freelance type. worker is the removed payroll split (structure_type_worker)
# and stays an Employee. contractor and freelance are external engagements;
# Interim is the only non-permanent type that is not student, intern,
# seasonal, apprenticeship or thesis. The legacy column keeps the original
# selection so this can be remapped.
_SELECTION_XMLID = {
    "employee": "contract_type_employee",
    "worker": "contract_type_employee",
    "student": "contract_type_student",
    "trainee": "contract_type_intern",
    "contractor": "contract_type_interim",
    "freelance": "contract_type_interim",
}

# Standard contract types removed from the 20.0 data file. A version that
# still points at one of them takes the selection instead. A version that
# points at a type 20.0 still ships (or a custom type) keeps that type:
# the selection defaults to "employee" and must not wipe Apprenticeship,
# Interim, and the other renamed contract types.
_OBSOLETE_CONTRACT_TYPES = (
    "contract_type_full_time",
    "contract_type_part_time",
    "contract_type_permanent",
    "contract_type_statutory",
    "contract_type_temporary",
)


def _map_employee_type_selection(cr):
    """Fill ``employee_type_id`` from the legacy ``employee_type`` selection."""
    legacy = openupgrade.get_legacy_name("employee_type")
    if not openupgrade.column_exists(cr, "hr_version", legacy):
        return
    if not openupgrade.column_exists(cr, "hr_version", "employee_type_id"):
        return
    case_sql = sql.SQL(" ").join(
        sql.SQL("WHEN {value} THEN {xmlid}").format(
            value=sql.Literal(key),
            xmlid=sql.Literal(xmlid),
        )
        for key, xmlid in _SELECTION_XMLID.items()
    )
    obsolete = sql.SQL(", ").join(
        sql.Literal(name) for name in _OBSOLETE_CONTRACT_TYPES
    )
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            UPDATE hr_version AS version
               SET employee_type_id = target.res_id
              FROM (
                    SELECT id,
                           CASE {legacy}
                                {cases}
                                ELSE 'contract_type_employee'
                           END AS xmlname
                      FROM hr_version
                     WHERE {legacy} IS NOT NULL
                   ) AS mapped
              JOIN ir_model_data AS target
                ON target.module = 'hr'
               AND target.name = mapped.xmlname
               AND target.model = 'hr.employee.type'
             WHERE version.id = mapped.id
               AND (
                    version.employee_type_id IS NULL
                    OR version.employee_type_id IN (
                        SELECT res_id
                          FROM ir_model_data
                         WHERE module = 'hr'
                           AND model = 'hr.employee.type'
                           AND name IN ({obsolete})
                    )
               )
            """
        ).format(
            legacy=sql.Identifier(legacy),
            cases=case_sql,
            obsolete=obsolete,
        ),
    )


def _create_departures(cr):
    """Departure columns on ``hr.version`` are now related to a new model.

    One ``hr.employee.departure`` is created per version that had a reason,
    a date or a description, and ``departure_id`` is set to it. Versions
    without an employee (contract templates) are left alone: the new model
    requires an employee.
    """
    reason = openupgrade.get_legacy_name("departure_reason_id")
    description = openupgrade.get_legacy_name("departure_description")
    date = openupgrade.get_legacy_name("departure_date")
    if not openupgrade.column_exists(cr, "hr_version", reason):
        return
    if not openupgrade.table_exists(cr, "hr_employee_departure"):
        _logger.warning(
            "hr.employee.departure does not exist yet; version departure "
            "values stay in %s / %s / %s.",
            reason,
            description,
            date,
        )
        return
    if not openupgrade.column_exists(cr, "hr_version", "departure_id"):
        openupgrade.logged_query(
            cr, "ALTER TABLE hr_version ADD COLUMN departure_id INTEGER"
        )
    link = openupgrade.get_legacy_name("version_id")
    if not openupgrade.column_exists(cr, "hr_employee_departure", link):
        openupgrade.logged_query(
            cr,
            sql.SQL("ALTER TABLE hr_employee_departure ADD COLUMN {} INTEGER").format(
                sql.Identifier(link)
            ),
        )
    if openupgrade.column_exists(cr, "hr_version", description):
        description_expr = sql.SQL("version.{}::text").format(
            sql.Identifier(description)
        )
        description_set = sql.SQL("version.{} IS NOT NULL").format(
            sql.Identifier(description)
        )
    else:
        description_expr = sql.SQL("NULL::text")
        description_set = sql.SQL("FALSE")
    if openupgrade.column_exists(cr, "hr_version", date):
        date_expr = sql.SQL("version.{}").format(sql.Identifier(date))
        date_set = sql.SQL("version.{} IS NOT NULL").format(sql.Identifier(date))
    else:
        date_expr = sql.SQL("NULL::date")
        date_set = sql.SQL("FALSE")
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            INSERT INTO hr_employee_departure (
                employee_id, departure_reason_id, departure_description,
                dismissal_date, departure_date, action_date,
                create_uid, write_uid, create_date, write_date, {link}
            )
            SELECT version.employee_id,
                   COALESCE(
                       version.{reason},
                       (SELECT id FROM hr_departure_reason ORDER BY id LIMIT 1)
                   ),
                   {description},
                   COALESCE({date}, CURRENT_DATE),
                   {date},
                   (COALESCE({date}, CURRENT_DATE) + INTERVAL '1 day')::date,
                   version.create_uid,
                   version.write_uid,
                   NOW() AT TIME ZONE 'UTC',
                   NOW() AT TIME ZONE 'UTC',
                   version.id
              FROM hr_version AS version
             WHERE version.employee_id IS NOT NULL
               AND (
                    version.{reason} IS NOT NULL
                    OR {date_set}
                    OR {description_set}
               )
               AND COALESCE(
                    version.{reason},
                    (SELECT id FROM hr_departure_reason ORDER BY id LIMIT 1)
               ) IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM hr_employee_departure AS existing
                     WHERE existing.{link} = version.id
               )
            """
        ).format(
            link=sql.Identifier(link),
            reason=sql.Identifier(reason),
            description=description_expr,
            date=date_expr,
            date_set=date_set,
            description_set=description_set,
        ),
    )
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            UPDATE hr_version AS version
               SET departure_id = departure.id
              FROM hr_employee_departure AS departure
             WHERE departure.{link} = version.id
               AND version.departure_id IS NULL
            """
        ).format(link=sql.Identifier(link)),
    )
    openupgrade.logged_query(
        cr,
        sql.SQL("ALTER TABLE hr_employee_departure DROP COLUMN {}").format(
            sql.Identifier(link)
        ),
    )


@openupgrade.migrate()
def migrate(env, version):
    _map_employee_type_selection(env.cr)
    _create_departures(env.cr)
    openupgrade.load_data(env, "hr", "20.0.1.1/noupdate_changes.xml")
