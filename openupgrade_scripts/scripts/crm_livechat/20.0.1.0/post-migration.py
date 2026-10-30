# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging

from openupgradelib import openupgrade
from psycopg2 import sql

_logger = logging.getLogger(__name__)


def _sql_table(name):
    parts = [part.replace('"', "") for part in name.split(".")]
    return sql.Identifier(*parts)


def _xmlid_res_id(cr, module, name):
    cr.execute(
        """
        SELECT res_id
        FROM ir_model_data
        WHERE module = %s AND name = %s AND model = 'utm.source'
        """,
        (module, name),
    )
    row = cr.fetchone()
    return row[0] if row else None


def _source_exists(cr, source_id):
    cr.execute("SELECT 1 FROM utm_source WHERE id = %s", (source_id,))
    return bool(cr.fetchone())


def _repoint_source_fks(cr, keep_id, drop_id):
    cr.execute(
        """
        SELECT c.conrelid::regclass::text, a.attname
        FROM pg_constraint AS c
        JOIN pg_attribute AS a
            ON a.attrelid = c.conrelid
            AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f'
            AND c.confrelid = 'utm_source'::regclass
            AND cardinality(c.conkey) = 1
        """
    )
    for table, column in cr.fetchall():
        if column == "id":
            continue
        query = sql.SQL("UPDATE {table} SET {column} = %s WHERE {column} = %s").format(
            table=_sql_table(table), column=sql.Identifier(column)
        )
        openupgrade.logged_query(cr, query, (keep_id, drop_id))
    openupgrade.logged_query(
        cr,
        """
        UPDATE ir_model_data
        SET res_id = %s
        WHERE model = 'utm.source'
            AND res_id = %s
            AND NOT (module = 'utm' AND name = 'utm_source_livechat')
        """,
        (keep_id, drop_id),
    )


def _merge_livechat_utm_source(env):
    """Point utm.utm_source_livechat at the historical Livechat source.

    utm 20.0 loads that xmlid (noupdate) before this module runs, so a
    database that already has crm_livechat.utm_source_livechat gets a
    second source, usually named "Livechat [2]". Keep the historical row.
    """
    cr = env.cr
    historical_id = _xmlid_res_id(cr, "crm_livechat", "utm_source_livechat")
    if not historical_id:
        return
    duplicate_id = _xmlid_res_id(cr, "utm", "utm_source_livechat")
    if not _source_exists(cr, historical_id):
        openupgrade.logged_query(
            cr,
            """
            DELETE FROM ir_model_data
            WHERE module = 'crm_livechat'
                AND name = 'utm_source_livechat'
                AND model = 'utm.source'
            """,
        )
        return
    if duplicate_id and duplicate_id != historical_id:
        _repoint_source_fks(cr, historical_id, duplicate_id)
        openupgrade.logged_query(
            cr,
            """
            DELETE FROM ir_model_data
            WHERE module = 'utm'
                AND name = 'utm_source_livechat'
                AND model = 'utm.source'
            """,
        )
        openupgrade.logged_query(
            cr,
            "DELETE FROM utm_source WHERE id = %s",
            (duplicate_id,),
        )
        _logger.info(
            "Merged duplicate utm.source %s into historical Livechat source %s.",
            duplicate_id,
            historical_id,
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE ir_model_data
        SET module = 'utm', name = 'utm_source_livechat', noupdate = TRUE
        WHERE module = 'crm_livechat'
            AND name = 'utm_source_livechat'
            AND model = 'utm.source'
        """,
    )


def _fill_chatbot_utm_reference(env):
    """Leads created by a chatbot used to store that bot's utm.source.

    v20 counts them with utm_reference = ``chatbot.script,<id>``
    (odoo/odoo@895154fd1725). The source_id column on chatbot.script is
    removed when im_livechat is updated, which is before this module, so
    the mapping is read from the table im_livechat's pre-migration saved.
    The per-script source_id on the lead is kept: it is still a valid
    source, and new leads use the shared Chatbot source instead.
    """
    cr = env.cr
    if not openupgrade.table_exists(cr, "ou_crm_livechat_chatbot_source"):
        _logger.info(
            "No chatbot source map; crm.lead.utm_reference was not backfilled."
        )
        return
    if not openupgrade.column_exists(cr, "crm_lead", "utm_reference"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE crm_lead
        SET utm_reference = 'chatbot.script,' || src.chatbot_script_id::text
        FROM (
            SELECT DISTINCT ON (source_id)
                source_id,
                chatbot_script_id
            FROM ou_crm_livechat_chatbot_source
            ORDER BY source_id, chatbot_script_id
        ) AS src
        WHERE crm_lead.source_id = src.source_id
            AND COALESCE(crm_lead.utm_reference, '') = ''
        """,
    )
    _logger.info(
        "Set utm_reference on %s leads created by a chatbot script.",
        cr.rowcount,
    )
    openupgrade.logged_query(cr, "DROP TABLE ou_crm_livechat_chatbot_source")


@openupgrade.migrate()
def migrate(env, version):
    _merge_livechat_utm_source(env)
    _fill_chatbot_utm_reference(env)
