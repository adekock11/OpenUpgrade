# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _fill_required_version_fields(cr):
    """``hr.version`` gains required stored ``tz`` and ``resource_calendar_id``.

    19.0 ``tz`` is related to the employee and is not stored on the version.
    20.0 stores it on the version and requires it. Working hours were optional
    and are now required. Company calendars cover the rows that have none.
    """
    if openupgrade.column_exists(cr, "hr_employee", "tz"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_employee
               SET tz = 'UTC'
             WHERE tz IS NULL
                OR btrim(tz) = ''
            """,
        )
    if not openupgrade.column_exists(cr, "hr_version", "tz"):
        openupgrade.logged_query(cr, "ALTER TABLE hr_version ADD COLUMN tz VARCHAR")
    if openupgrade.column_exists(cr, "hr_employee", "tz") and openupgrade.column_exists(
        cr, "hr_version", "employee_id"
    ):
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_version AS version
               SET tz = employee.tz
              FROM hr_employee AS employee
             WHERE version.employee_id = employee.id
               AND (version.tz IS NULL OR btrim(version.tz) = '')
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE hr_version
           SET tz = 'UTC'
         WHERE tz IS NULL
            OR btrim(tz) = ''
        """,
    )
    if openupgrade.column_exists(cr, "hr_version", "resource_calendar_id"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_version AS version
               SET resource_calendar_id = company.resource_calendar_id
              FROM res_company AS company
             WHERE version.resource_calendar_id IS NULL
               AND version.company_id = company.id
               AND company.resource_calendar_id IS NOT NULL
            """,
        )
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_version
               SET resource_calendar_id = (
                    SELECT id FROM resource_calendar ORDER BY id LIMIT 1
                   )
             WHERE resource_calendar_id IS NULL
               AND EXISTS (SELECT 1 FROM resource_calendar)
            """,
        )


def _fill_required_job_company(cr):
    """``hr.job.company_id`` is required in 20.0."""
    if not openupgrade.column_exists(cr, "hr_job", "company_id"):
        return
    if openupgrade.column_exists(cr, "hr_department", "company_id"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_job AS job
               SET company_id = department.company_id
              FROM hr_department AS department
             WHERE job.company_id IS NULL
               AND job.department_id = department.id
               AND department.company_id IS NOT NULL
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE hr_job
           SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
         WHERE company_id IS NULL
           AND EXISTS (SELECT 1 FROM res_company)
        """,
    )


def _copy_employee_stored_fields(cr):
    """Fields that moved from the related version onto ``hr.employee``.

    ``additional_note`` is deleted from ``hr.version`` and stored on the
    employee. ``contract_template_id`` stops being a related field. The value
    copied is the employee's current version (``version_id``).
    """
    if not openupgrade.column_exists(cr, "hr_employee", "version_id"):
        return
    if openupgrade.column_exists(cr, "hr_version", "additional_note"):
        if not openupgrade.column_exists(cr, "hr_employee", "additional_note"):
            openupgrade.logged_query(
                cr, "ALTER TABLE hr_employee ADD COLUMN additional_note TEXT"
            )
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_employee AS employee
               SET additional_note = version.additional_note
              FROM hr_version AS version
             WHERE employee.version_id = version.id
               AND employee.additional_note IS NULL
               AND version.additional_note IS NOT NULL
            """,
        )
    if openupgrade.column_exists(cr, "hr_version", "contract_template_id"):
        if not openupgrade.column_exists(cr, "hr_employee", "contract_template_id"):
            openupgrade.logged_query(
                cr, "ALTER TABLE hr_employee ADD COLUMN contract_template_id INTEGER"
            )
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_employee AS employee
               SET contract_template_id = version.contract_template_id
              FROM hr_version AS version
             WHERE employee.version_id = version.id
               AND employee.contract_template_id IS NULL
               AND version.contract_template_id IS NOT NULL
            """,
        )


def _map_recruiter(cr):
    """``hr.job.user_id`` (res.users) becomes ``recruiter_id`` (hr.employee).

    The employee of that user, preferring the job's company, is stored on the
    new column. Jobs whose user has no employee keep a NULL recruiter (the
    field is not required).
    """
    if not openupgrade.column_exists(cr, "hr_job", "user_id"):
        return
    if not openupgrade.column_exists(cr, "hr_job", "recruiter_id"):
        openupgrade.logged_query(
            cr, "ALTER TABLE hr_job ADD COLUMN recruiter_id INTEGER"
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE hr_job AS job
           SET recruiter_id = (
                SELECT employee.id
                  FROM hr_employee AS employee
                 WHERE employee.user_id = job.user_id
                 ORDER BY
                       (employee.company_id IS NOT DISTINCT FROM job.company_id) DESC,
                       employee.id
                 LIMIT 1
               )
         WHERE job.user_id IS NOT NULL
           AND job.recruiter_id IS NULL
        """,
    )


def _rename_contract_type(env):
    """``hr.contract.type`` is ``hr.employee.type`` in 20.0.

    The same xmlids (``hr.contract_type_*``) are reused. ``contract_type_id``
    on jobs and versions is renamed to ``employee_type_id``. The selection
    ``hr.version.employee_type`` is kept in a legacy column and applied in
    post-migration where it carries information the contract type does not.
    """
    cr = env.cr
    if openupgrade.table_exists(cr, "hr_contract_type"):
        openupgrade.rename_models(cr, [("hr.contract.type", "hr.employee.type")])
        openupgrade.rename_tables(cr, [("hr_contract_type", "hr_employee_type")])
    openupgrade.logged_query(
        cr,
        """
        UPDATE ir_model_data
           SET model = 'hr.employee.type'
         WHERE model = 'hr.contract.type'
        """,
    )
    openupgrade.rename_fields(
        env,
        [
            ("hr.job", "hr_job", "contract_type_id", "employee_type_id"),
            ("hr.version", "hr_version", "contract_type_id", "employee_type_id"),
        ],
    )
    if openupgrade.column_exists(cr, "ir_act_window", "res_model"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE ir_act_window
               SET res_model = 'hr.employee.type'
             WHERE res_model = 'hr.contract.type'
            """,
        )
    if openupgrade.column_exists(cr, "ir_ui_view", "model"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE ir_ui_view
               SET model = 'hr.employee.type'
             WHERE model = 'hr.contract.type'
            """,
        )
    if openupgrade.column_exists(cr, "ir_ui_view", "arch_db"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE ir_ui_view
               SET arch_db = replace(
                    arch_db::text, 'hr.contract.type', 'hr.employee.type'
                   )::jsonb
             WHERE arch_db::text LIKE %s
            """,
            ("%hr.contract.type%",),
        )


def _preserve_version_values(cr):
    """Keep values that 20.0 stops storing on ``hr.version``.

    ``employee_type`` is replaced by ``employee_type_id``. Departure columns
    become related to the new ``hr.employee.departure`` model and are rebuilt
    from these copies in post-migration. ``sex = other`` is no longer a
    selection key; the column is cleared because the field is not required.
    """
    spec = {}
    version_columns = []
    for column in (
        "employee_type",
        "departure_reason_id",
        "departure_description",
        "departure_date",
    ):
        if openupgrade.column_exists(cr, "hr_version", column):
            version_columns.append((column, None, None))
    if version_columns:
        spec["hr_version"] = version_columns
    if spec:
        openupgrade.copy_columns(cr, spec)
    if openupgrade.column_exists(cr, "hr_version", "sex"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE hr_version
               SET sex = NULL
             WHERE sex = 'other'
            """,
        )


@openupgrade.migrate()
def migrate(env, version):
    cr = env.cr
    if not openupgrade.table_exists(cr, "hr_version"):
        return
    _fill_required_version_fields(cr)
    _fill_required_job_company(cr)
    _copy_employee_stored_fields(cr)
    _map_recruiter(cr)
    _preserve_version_values(cr)
    _rename_contract_type(env)
