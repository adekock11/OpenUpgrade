# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging

from openupgradelib import openupgrade
from psycopg2 import sql

_logger = logging.getLogger(__name__)


def _sql_table(name):
    parts = [part.replace('"', "") for part in name.split(".")]
    return sql.Identifier(*parts)


def _industry_fks(cr):
    cr.execute(
        """
        SELECT c.conrelid::regclass::text, a.attname, a.attnotnull
        FROM pg_constraint AS c
        JOIN pg_attribute AS a
            ON a.attrelid = c.conrelid
            AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f'
            AND c.confrelid = 'crm_iap_lead_industry'::regclass
            AND cardinality(c.conkey) = 1
        """
    )
    return cr.fetchall()


def _table_columns(cr, table):
    cr.execute(
        """
        SELECT attname
        FROM pg_attribute
        WHERE attrelid = %s::regclass
            AND attnum > 0
            AND NOT attisdropped
        """,
        (table.replace('"', ""),),
    )
    return {row[0] for row in cr.fetchall()}


def _deactivate_reveal_rules(cr, rel_table, industry_column):
    """An empty industry filter means "match every industry".

    Rules that had a v19 reveal-industry filter cannot be translated to SIC
    groups (odoo/odoo@57b8a7d360). Deactivate them instead of widening a
    paid IAP cron to every visitor.
    """
    if not openupgrade.table_exists(cr, "crm_reveal_rule"):
        return
    query = sql.SQL(
        """
        UPDATE crm_reveal_rule
        SET active = FALSE
        WHERE active
            AND id IN (
                SELECT crm_reveal_rule_id
                FROM {rel}
                WHERE {industry} IS NOT NULL
            )
        """
    ).format(
        rel=_sql_table(rel_table),
        industry=sql.Identifier(industry_column),
    )
    openupgrade.logged_query(cr, query)
    _logger.info(
        "Deactivated %s crm.reveal.rule rows; their industry filter used "
        "the removed reveal catalog.",
        cr.rowcount,
    )


def _drop_industry_links(cr):
    for table, column, not_null in _industry_fks(cr):
        columns = _table_columns(cr, table)
        if "crm_reveal_rule_id" in columns and table != "crm_reveal_rule":
            _deactivate_reveal_rules(cr, table, column)
            openupgrade.logged_query(
                cr,
                sql.SQL("DELETE FROM {rel}").format(rel=_sql_table(table)),
            )
            continue
        if table == "crm_reveal_rule":
            _deactivate_reveal_rules_m2o(cr, column)
            continue
        if not_null:
            openupgrade.logged_query(
                cr,
                sql.SQL("DELETE FROM {rel}").format(rel=_sql_table(table)),
            )
        else:
            openupgrade.logged_query(
                cr,
                sql.SQL("UPDATE {rel} SET {column} = NULL").format(
                    rel=_sql_table(table),
                    column=sql.Identifier(column),
                ),
            )


def _deactivate_reveal_rules_m2o(cr, column):
    query = sql.SQL(
        """
        UPDATE crm_reveal_rule
        SET active = FALSE
        WHERE active AND {column} IS NOT NULL
        """
    ).format(column=sql.Identifier(column))
    openupgrade.logged_query(cr, query)
    openupgrade.logged_query(
        cr,
        sql.SQL("UPDATE crm_reveal_rule SET {column} = NULL").format(
            column=sql.Identifier(column)
        ),
    )


def _purge_v19_industries(env):
    """Replace the reveal-id industry catalog with the SIC catalog.

    v19 rows are keyed by IAP reveal ids. v20 rows are SIC major groups
    with a required division (odoo/odoo@57b8a7d360). There is no published
    mapping. Old rows are removed so the module data can load the new
    catalog, and links from mining requests are cleared. People-search
    columns on crm.iap.lead.mining.request are left in the table: Odoo 20
    does not drop removed columns, and v20 has no field for them.
    """
    cr = env.cr
    if not openupgrade.column_exists(cr, "crm_iap_lead_industry", "reveal_ids"):
        return
    _drop_industry_links(cr)
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM ir_model_data
        WHERE model = 'crm.iap.lead.industry'
        """,
    )
    openupgrade.logged_query(cr, "DELETE FROM crm_iap_lead_industry")
    _logger.info("Removed the v19 reveal industry catalog (%s rows).", cr.rowcount)
    openupgrade.logged_query(
        cr,
        "ALTER TABLE crm_iap_lead_industry DROP COLUMN reveal_ids",
    )


@openupgrade.migrate()
def migrate(env, version):
    _purge_v19_industries(env)
