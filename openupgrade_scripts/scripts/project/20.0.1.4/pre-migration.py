# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)

# Historical stage time, rebuilt from mail.tracking.value into the v20 stored
# shape {"d": "<utc datetime entered current stage>", "s": <stage id or 0>,
# "<stage id>": <minutes spent on previous visits>}.
# See odoo/odoo@d5e8a68f4b. Values are minutes, not the seconds the v19
# non-stored compute used. The open visit of the current stage is left out:
# v20 adds it at read time from "d".
_TASK_DURATION_QUERY = """
UPDATE project_task AS rec
SET duration_tracking = src.payload
FROM (
    SELECT src.id,
        COALESCE(hist.hist, '{}'::jsonb) || jsonb_build_object(
            's', COALESCE(src.stage_id, 0),
            'd', to_char(
                COALESCE(
                    entered.last_date,
                    src.create_date,
                    (NOW() AT TIME ZONE 'UTC')
                ),
                'YYYY-MM-DD HH24:MI:SS'
            )
        ) AS payload
    FROM project_task AS src
    LEFT JOIN (
        SELECT summed.res_id,
            jsonb_object_agg(summed.stage_id::text, summed.minutes) AS hist
        FROM (
            SELECT intervals.res_id,
                intervals.stage_id,
                SUM(intervals.minutes)::int AS minutes
            FROM (
                SELECT ordered.res_id,
                    ordered.stage_id,
                    GREATEST(
                        0,
                        FLOOR(
                            EXTRACT(
                                EPOCH FROM (
                                    ordered.create_date - COALESCE(
                                        ordered.prev_date, task.create_date
                                    )
                                )
                            ) / 60.0
                        )
                    )::int AS minutes
                FROM (
                    SELECT tracking.res_id,
                        tracking.stage_id,
                        tracking.create_date,
                        LAG(tracking.create_date) OVER (
                            PARTITION BY tracking.res_id
                            ORDER BY tracking.tracking_id
                        ) AS prev_date
                    FROM (
                        SELECT message.res_id,
                            value.id AS tracking_id,
                            value.create_date,
                            COALESCE(value.old_value_integer, 0) AS stage_id
                        FROM mail_tracking_value AS value
                        JOIN mail_message AS message
                            ON message.id = value.mail_message_id
                        JOIN ir_model_fields AS field
                            ON field.id = value.field_id
                            AND field.model = 'project.task'
                            AND field.name = 'stage_id'
                        WHERE message.model = 'project.task'
                            AND message.res_id IS NOT NULL
                    ) AS tracking
                ) AS ordered
                JOIN project_task AS task ON task.id = ordered.res_id
            ) AS intervals
            GROUP BY intervals.res_id, intervals.stage_id
            HAVING SUM(intervals.minutes) > 0
        ) AS summed
        GROUP BY summed.res_id
    ) AS hist ON hist.res_id = src.id
    LEFT JOIN (
        SELECT message.res_id, MAX(value.create_date) AS last_date
        FROM mail_tracking_value AS value
        JOIN mail_message AS message
            ON message.id = value.mail_message_id
        JOIN ir_model_fields AS field
            ON field.id = value.field_id
            AND field.model = 'project.task'
            AND field.name = 'stage_id'
        WHERE message.model = 'project.task'
            AND message.res_id IS NOT NULL
        GROUP BY message.res_id
    ) AS entered ON entered.res_id = src.id
) AS src
WHERE rec.id = src.id
"""

_PROJECT_DURATION_QUERY = """
UPDATE project_project AS rec
SET duration_tracking = src.payload,
    date_last_stage_update = src.stage_date
FROM (
    SELECT src.id,
        COALESCE(
            entered.last_date,
            src.create_date,
            (NOW() AT TIME ZONE 'UTC')
        ) AS stage_date,
        COALESCE(hist.hist, '{}'::jsonb) || jsonb_build_object(
            's', COALESCE(src.stage_id, 0),
            'd', to_char(
                COALESCE(
                    entered.last_date,
                    src.create_date,
                    (NOW() AT TIME ZONE 'UTC')
                ),
                'YYYY-MM-DD HH24:MI:SS'
            )
        ) AS payload
    FROM project_project AS src
    LEFT JOIN (
        SELECT summed.res_id,
            jsonb_object_agg(summed.stage_id::text, summed.minutes) AS hist
        FROM (
            SELECT intervals.res_id,
                intervals.stage_id,
                SUM(intervals.minutes)::int AS minutes
            FROM (
                SELECT ordered.res_id,
                    ordered.stage_id,
                    GREATEST(
                        0,
                        FLOOR(
                            EXTRACT(
                                EPOCH FROM (
                                    ordered.create_date - COALESCE(
                                        ordered.prev_date, project.create_date
                                    )
                                )
                            ) / 60.0
                        )
                    )::int AS minutes
                FROM (
                    SELECT tracking.res_id,
                        tracking.stage_id,
                        tracking.create_date,
                        LAG(tracking.create_date) OVER (
                            PARTITION BY tracking.res_id
                            ORDER BY tracking.tracking_id
                        ) AS prev_date
                    FROM (
                        SELECT message.res_id,
                            value.id AS tracking_id,
                            value.create_date,
                            COALESCE(value.old_value_integer, 0) AS stage_id
                        FROM mail_tracking_value AS value
                        JOIN mail_message AS message
                            ON message.id = value.mail_message_id
                        JOIN ir_model_fields AS field
                            ON field.id = value.field_id
                            AND field.model = 'project.project'
                            AND field.name = 'stage_id'
                        WHERE message.model = 'project.project'
                            AND message.res_id IS NOT NULL
                    ) AS tracking
                ) AS ordered
                JOIN project_project AS project ON project.id = ordered.res_id
            ) AS intervals
            GROUP BY intervals.res_id, intervals.stage_id
            HAVING SUM(intervals.minutes) > 0
        ) AS summed
        GROUP BY summed.res_id
    ) AS hist ON hist.res_id = src.id
    LEFT JOIN (
        SELECT message.res_id, MAX(value.create_date) AS last_date
        FROM mail_tracking_value AS value
        JOIN mail_message AS message
            ON message.id = value.mail_message_id
        JOIN ir_model_fields AS field
            ON field.id = value.field_id
            AND field.model = 'project.project'
            AND field.name = 'stage_id'
        WHERE message.model = 'project.project'
            AND message.res_id IS NOT NULL
        GROUP BY message.res_id
    ) AS entered ON entered.res_id = src.id
) AS src
WHERE rec.id = src.id
"""


def _preserve_email_cc_on(env, table):
    """Append email_cc into description, then drop the column.

    mail.thread.cc is removed in 20.0 (odoo/odoo@3c26c0553754). project.task
    redeclared email_cc in 19 and drops that declaration in 20. project.update
    inherited the mixin and now inherits mail.thread only. Neither model has
    another place for the addresses. Module reflection does not drop the
    column, so it would sit unread. Same preservation as crm.lead: HTML-escape
    the value and append it to the Html description.
    """
    if not openupgrade.column_exists(env.cr, table, "email_cc"):
        return
    if table == "project_task":
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE project_task
            SET description = CONCAT(
                COALESCE(description, ''),
                CASE
                    WHEN COALESCE(description, '') = '' THEN ''
                    ELSE '<br/>'
                END,
                '<p>Email cc preserved from previous version: ',
                replace(
                    replace(replace(btrim(email_cc), '&', '&amp;'), '<', '&lt;'),
                    '>',
                    '&gt;'
                ),
                '</p>'
            )
            WHERE COALESCE(btrim(email_cc), '') <> ''
                AND strpos(
                    COALESCE(description, ''),
                    'Email cc preserved from previous version:'
                ) = 0
            """,
        )
    elif table == "project_update":
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE project_update
            SET description = CONCAT(
                COALESCE(description, ''),
                CASE
                    WHEN COALESCE(description, '') = '' THEN ''
                    ELSE '<br/>'
                END,
                '<p>Email cc preserved from previous version: ',
                replace(
                    replace(replace(btrim(email_cc), '&', '&amp;'), '<', '&lt;'),
                    '>',
                    '&gt;'
                ),
                '</p>'
            )
            WHERE COALESCE(btrim(email_cc), '') <> ''
                AND strpos(
                    COALESCE(description, ''),
                    'Email cc preserved from previous version:'
                ) = 0
            """,
        )
    else:
        raise ValueError(table)
    _logger.info(
        "Preserved email_cc on %s %s rows into description.",
        env.cr.rowcount,
        table,
    )
    if table == "project_task":
        openupgrade.logged_query(
            env.cr, "ALTER TABLE project_task DROP COLUMN email_cc"
        )
    else:
        openupgrade.logged_query(
            env.cr, "ALTER TABLE project_update DROP COLUMN email_cc"
        )


def _preserve_email_cc(env):
    _preserve_email_cc_on(env, "project_task")
    _preserve_email_cc_on(env, "project_update")


def _migrate_collaborator_access_mode(env):
    """Map project.collaborator.limited_access onto access_mode.

    v19 stored a boolean. The share wizard exposed it as:

    * limited_access False ("Edit"): write every task, including stage and
      priority. That is v20 ``advanced_edit``.
    * limited_access True ("Edit with limited access"): write followed tasks.
      v20 dropped the row-level split and made ``edit`` the limited mode
      (no stage, no priority). See odoo/odoo@a59b237f77 and @04e9a2509d.

    NULL is treated as False, which was the field default.
    The column is filled before the ORM creates the required selection, so
    existing rows do not fall through to the new default ``view``.
    """
    if not openupgrade.column_exists(env.cr, "project_collaborator", "limited_access"):
        return
    openupgrade.add_columns(
        env,
        [
            (
                "project.collaborator",
                "access_mode",
                "selection",
                None,
                "project_collaborator",
                "varchar",
            ),
        ],
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE project_collaborator
        SET access_mode = CASE
            WHEN limited_access THEN 'edit'
            ELSE 'advanced_edit'
        END
        WHERE access_mode IS NULL
        """,
    )


def _fill_allowed_internal_users(env):
    """Copy private-project followers into allowed_internal_user_ids.

    v19 granted internal users access to follower-only projects through
    message_partner_ids. v20 grants it through the Team Members m2m and no
    longer looks at followers (odoo/odoo@bae4e441d9). Without this copy,
    internal followers of ``followers`` and ``invited_users`` projects lose
    the project. ``employees`` and ``portal`` stay visible to every internal
    user, so those followers are not copied.

    The relation table is created here. Many2many.update_db only queues the
    stored compute when the table is missing; pre-creating it keeps that
    compute from replacing these rows with just the project manager. The
    manager is inserted as well, which is what that compute would have added.
    Users outside the project company are skipped, matching
    ``_compute_allowed_internal_user_ids``.
    """
    openupgrade.logged_query(
        env.cr,
        """
        CREATE TABLE IF NOT EXISTS project_allowed_internal_users_rel (
            project_project_id INTEGER NOT NULL,
            res_users_id INTEGER NOT NULL,
            PRIMARY KEY (project_project_id, res_users_id)
        )
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        CREATE INDEX IF NOT EXISTS
            project_allowed_internal_users_rel_res_users_id_idx
        ON project_allowed_internal_users_rel
            (res_users_id, project_project_id)
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO project_allowed_internal_users_rel
            (project_project_id, res_users_id)
        SELECT DISTINCT project.id, users.id
        FROM project_project AS project
        JOIN mail_followers AS follower
            ON follower.res_model = 'project.project'
            AND follower.res_id = project.id
        JOIN res_users AS users
            ON users.partner_id = follower.partner_id
            AND users.share IS NOT TRUE
        WHERE project.privacy_visibility IN ('followers', 'invited_users')
            AND (
                project.company_id IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM res_company_users_rel AS rel
                    WHERE rel.user_id = users.id
                        AND rel.cid = project.company_id
                )
            )
        UNION
        SELECT project.id, users.id
        FROM project_project AS project
        JOIN res_users AS users
            ON users.id = project.user_id
            AND users.share IS NOT TRUE
        WHERE project.privacy_visibility IN ('followers', 'invited_users')
            AND (
                project.company_id IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM res_company_users_rel AS rel
                    WHERE rel.user_id = users.id
                        AND rel.cid = project.company_id
                )
            )
        ON CONFLICT DO NOTHING
        """,
    )


def _fill_view_collaborators(env):
    """Turn external project followers into read-only collaborators.

    v19 portal project access was "follower of this commercial entity".
    v20 requires a project.collaborator row (odoo/odoo@a59b237f77). Followers
    who are not already collaborators become ``access_mode = view``.

    Two sets are inserted:

    * the follower partner itself, when it is a share partner (portal user or
      a customer who will sign up later);
    * every existing portal user of that follower's commercial entity, because
      the v19 rule used ``child_of`` the commercial partner rather than the
      follower partner alone.
    """
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO project_collaborator (
            project_id, partner_id, access_mode,
            create_uid, write_uid, create_date, write_date
        )
        SELECT DISTINCT
            project.id,
            partner.id,
            'view',
            1,
            1,
            (NOW() AT TIME ZONE 'UTC'),
            (NOW() AT TIME ZONE 'UTC')
        FROM project_project AS project
        JOIN mail_followers AS follower
            ON follower.res_model = 'project.project'
            AND follower.res_id = project.id
        JOIN res_partner AS partner
            ON partner.id = follower.partner_id
            AND partner.partner_share IS TRUE
        WHERE project.privacy_visibility IN ('invited_users', 'portal')
            AND NOT EXISTS (
                SELECT 1
                FROM project_collaborator AS existing
                WHERE existing.project_id = project.id
                    AND existing.partner_id = partner.id
            )
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO project_collaborator (
            project_id, partner_id, access_mode,
            create_uid, write_uid, create_date, write_date
        )
        SELECT DISTINCT
            project.id,
            portal_user.partner_id,
            'view',
            1,
            1,
            (NOW() AT TIME ZONE 'UTC'),
            (NOW() AT TIME ZONE 'UTC')
        FROM project_project AS project
        JOIN mail_followers AS follower
            ON follower.res_model = 'project.project'
            AND follower.res_id = project.id
        JOIN res_partner AS followed
            ON followed.id = follower.partner_id
        JOIN res_partner AS portal_partner
            ON portal_partner.commercial_partner_id
                = followed.commercial_partner_id
        JOIN res_users AS portal_user
            ON portal_user.partner_id = portal_partner.id
            AND portal_user.share IS TRUE
        WHERE project.privacy_visibility IN ('invited_users', 'portal')
            AND NOT EXISTS (
                SELECT 1
                FROM project_collaborator AS existing
                WHERE existing.project_id = project.id
                    AND existing.partner_id = portal_user.partner_id
            )
        """,
    )


def _migrate_duration_tracking(env):
    """Pre-create stored duration_tracking so the ORM does not recompute it.

    The v20 compute only continues from the JSON already stored. An empty
    column would drop the history that v19 calculated from mail.tracking.value.
    """
    openupgrade.add_columns(
        env,
        [
            (
                "project.task",
                "duration_tracking",
                "json",
                None,
                "project_task",
                "jsonb",
            ),
            (
                "project.project",
                "duration_tracking",
                "json",
                None,
                "project_project",
                "jsonb",
            ),
            (
                "project.project",
                "date_last_stage_update",
                "datetime",
                None,
                "project_project",
                "timestamp",
            ),
        ],
    )
    openupgrade.logged_query(env.cr, _TASK_DURATION_QUERY)
    openupgrade.logged_query(env.cr, _PROJECT_DURATION_QUERY)


@openupgrade.migrate()
def migrate(env, version):
    _preserve_email_cc(env)
    _migrate_collaborator_access_mode(env)
    _fill_view_collaborators(env)
    _fill_allowed_internal_users(env)
    _migrate_duration_tracking(env)
