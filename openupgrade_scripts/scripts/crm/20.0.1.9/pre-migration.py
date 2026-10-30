# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def _preserve_email_cc(env):
    """Keep crm.lead email_cc, which mail.thread.cc used to store.

    The mixin is gone in 20.0 (odoo/odoo@3c26c0553754) and nothing else
    holds those addresses. Append them to the lead description, then drop
    the column so it is not an invisible leftover.
    """
    if not openupgrade.column_exists(env.cr, "crm_lead", "email_cc"):
        return
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE crm_lead
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
        """,
    )
    _logger.info(
        "Preserved email_cc on %s crm.lead rows into description.",
        env.cr.rowcount,
    )
    openupgrade.logged_query(env.cr, "ALTER TABLE crm_lead DROP COLUMN email_cc")


def _fill_duration_tracking(env):
    """Fill stored duration_tracking before the ORM recomputes it.

    v19 rebuilt a non-stored ``{stage_id: seconds}`` map from
    mail.tracking.value on every read. v20 stores
    ``{"s", "d", "<stage_id>": minutes}`` and the compute only rolls that
    dict forward (odoo/odoo@d5e8a68f4b). Recomputing NULL keeps the current
    stage and drops history. Completed visits are stored as minutes; the
    open visit stays in ``d`` (date_last_stage_update), which is what the
    web client adds on top of the stored map.
    """
    if not openupgrade.column_exists(env.cr, "crm_lead", "duration_tracking"):
        openupgrade.logged_query(
            env.cr,
            "ALTER TABLE crm_lead ADD COLUMN duration_tracking jsonb",
        )
    openupgrade.logged_query(
        env.cr,
        """
        WITH stage_field AS (
            SELECT id
            FROM ir_model_fields
            WHERE model = 'crm.lead' AND name = 'stage_id'
            ORDER BY id
            LIMIT 1
        ),
        changes AS (
            SELECT
                m.res_id,
                v.id AS tracking_id,
                v.create_date AS change_date,
                COALESCE(v.old_value_integer, 0) AS old_stage_id
            FROM mail_tracking_value v
            JOIN mail_message m ON m.id = v.mail_message_id
            WHERE v.field_id = (SELECT id FROM stage_field)
                AND m.model = 'crm.lead'
                AND m.res_id IS NOT NULL
        ),
        ordered_changes AS (
            SELECT
                changes.res_id,
                changes.old_stage_id,
                changes.change_date,
                LAG(changes.change_date) OVER (
                    PARTITION BY changes.res_id
                    ORDER BY changes.tracking_id
                ) AS prev_change_date
            FROM changes
        ),
        intervals AS (
            SELECT
                ordered_changes.res_id,
                ordered_changes.old_stage_id AS stage_id,
                GREATEST(
                    0,
                    FLOOR(
                        EXTRACT(
                            EPOCH FROM (
                                ordered_changes.change_date - COALESCE(
                                    ordered_changes.prev_change_date,
                                    crm_lead.create_date,
                                    ordered_changes.change_date
                                )
                            )
                        ) / 60
                    )
                )::int AS minutes
            FROM ordered_changes
            JOIN crm_lead ON crm_lead.id = ordered_changes.res_id
        ),
        spent AS (
            SELECT res_id, jsonb_object_agg(stage_id::text, minutes) AS payload
            FROM (
                SELECT res_id, stage_id, SUM(minutes)::int AS minutes
                FROM intervals
                GROUP BY res_id, stage_id
                HAVING SUM(minutes) > 0
            ) grouped
            GROUP BY res_id
        )
        UPDATE crm_lead
        SET duration_tracking =
            COALESCE(spent.payload, '{}'::jsonb)
            || jsonb_build_object(
                's', COALESCE(crm_lead.stage_id, 0),
                'd', to_char(
                    COALESCE(
                        crm_lead.date_last_stage_update,
                        crm_lead.create_date,
                        timezone('UTC', now())
                    ),
                    'YYYY-MM-DD HH24:MI:SS'
                )
            )
        FROM (
            SELECT id
            FROM crm_lead
            WHERE duration_tracking IS NULL
        ) todo
        LEFT JOIN spent ON spent.res_id = todo.id
        WHERE crm_lead.id = todo.id
        """,
    )


def _migrate_assignment_optout(env):
    """Map team-member opt-out onto assignment_max = 0.

    v20 drops assignment_optout. ``assignment_rules`` is a non-stored
    compute: max >= 30000 is unlimited, max == 0 is opt-out, anything else
    is limited (odoo/odoo@553fbd1afa). Existing caps stay as "limited".
    """
    if not openupgrade.column_exists(env.cr, "crm_team_member", "assignment_optout"):
        return
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE crm_team_member
        SET assignment_max = 0
        WHERE assignment_optout
        """,
    )
    _logger.info(
        "Opted %s crm.team.member rows out of assignment (assignment_max=0).",
        env.cr.rowcount,
    )
    openupgrade.logged_query(
        env.cr,
        "ALTER TABLE crm_team_member DROP COLUMN assignment_optout",
    )


@openupgrade.migrate()
def migrate(env, version):
    _preserve_email_cc(env)
    _fill_duration_tracking(env)
    _migrate_assignment_optout(env)
