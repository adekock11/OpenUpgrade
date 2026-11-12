# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade
from psycopg2 import sql

_logger = logging.getLogger(__name__)

_REL_TABLE = "payment_method_payment_provider_rel"


def _payment_method_fks(cr):
    """Foreign keys that point at ``payment_method.id``."""
    cr.execute(
        """
        SELECT src.relname, att.attname
          FROM pg_constraint AS con
          JOIN pg_class AS src ON src.oid = con.conrelid
          JOIN pg_class AS dst ON dst.oid = con.confrelid
          JOIN pg_namespace AS ns ON ns.oid = src.relnamespace
          JOIN pg_attribute AS att
            ON att.attrelid = src.oid
           AND att.attnum = con.conkey[1]
         WHERE con.contype = 'f'
           AND dst.relname = 'payment_method'
           AND ns.nspname = current_schema()
           AND array_length(con.conkey, 1) = 1
        """
    )
    return [
        (table, column) for table, column in cr.fetchall() if table != "payment_method"
    ]


def _assign_provider_from_relation(cr):
    """One method row per provider.

    19.0 links ``payment.method`` and ``payment.provider`` with the many2many
    ``payment_method_payment_provider_rel`` (both ``provider_ids`` and
    ``payment_method_ids`` use that table). 20.0 stores a required
    ``provider_id`` and a unique ``(provider_id, code)``. The lowest provider
    id keeps the existing row. Further providers get a copy, and transactions
    and tokens follow the provider they were paid with.
    """
    if not openupgrade.table_exists(cr, _REL_TABLE):
        return
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            UPDATE payment_method AS method
               SET provider_id = chosen.payment_provider_id
              FROM (
                    SELECT DISTINCT ON (payment_method_id)
                           payment_method_id,
                           payment_provider_id
                      FROM {rel}
                     ORDER BY payment_method_id, payment_provider_id
                   ) AS chosen
             WHERE method.id = chosen.payment_method_id
               AND method.provider_id IS NULL
            """
        ).format(rel=sql.Identifier(_REL_TABLE)),
    )
    source = openupgrade.get_legacy_name("source_method_id")
    if not openupgrade.column_exists(cr, "payment_method", source):
        openupgrade.logged_query(
            cr,
            sql.SQL("ALTER TABLE payment_method ADD COLUMN {} INTEGER").format(
                sql.Identifier(source)
            ),
        )
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'payment_method'
           AND column_name NOT IN ('id', 'provider_id')
         ORDER BY ordinal_position
        """
    )
    columns = [row[0] for row in cr.fetchall() if row[0] != source]
    column_sql = sql.SQL(", ").join(sql.Identifier(name) for name in columns)
    select_sql = sql.SQL(", ").join(
        sql.SQL("method.{}").format(sql.Identifier(name)) for name in columns
    )
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            INSERT INTO payment_method ({columns}, provider_id, {source})
            SELECT {select_sql}, rel.payment_provider_id, method.id
              FROM payment_method AS method
              JOIN {rel} AS rel
                ON rel.payment_method_id = method.id
             WHERE rel.payment_provider_id IS DISTINCT FROM method.provider_id
               AND NOT EXISTS (
                    SELECT 1
                      FROM payment_method AS existing
                     WHERE existing.provider_id = rel.payment_provider_id
                       AND existing.code = method.code
                       AND existing.id <> method.id
                   )
            """
        ).format(
            columns=column_sql,
            source=sql.Identifier(source),
            select_sql=select_sql,
            rel=sql.Identifier(_REL_TABLE),
        ),
    )
    # Transactions and tokens of the extra providers follow the copy.
    for table in ("payment_transaction", "payment_token"):
        if not openupgrade.column_exists(cr, table, "payment_method_id"):
            continue
        if not openupgrade.column_exists(cr, table, "provider_id"):
            continue
        openupgrade.logged_query(
            cr,
            sql.SQL(
                """
                UPDATE {table} AS record
                   SET payment_method_id = copy.id
                  FROM payment_method AS copy
                 WHERE copy.{source} = record.payment_method_id
                   AND copy.provider_id = record.provider_id
                """
            ).format(table=sql.Identifier(table), source=sql.Identifier(source)),
        )
    if openupgrade.column_exists(cr, "payment_method", "primary_payment_method_id"):
        openupgrade.logged_query(
            cr,
            sql.SQL(
                """
                UPDATE payment_method AS copy
                   SET primary_payment_method_id = primary_copy.id
                  FROM payment_method AS primary_copy
                 WHERE copy.{source} IS NOT NULL
                   AND primary_copy.{source} = copy.primary_payment_method_id
                   AND primary_copy.provider_id = copy.provider_id
                """
            ).format(source=sql.Identifier(source)),
        )
    openupgrade.logged_query(
        cr,
        sql.SQL("ALTER TABLE payment_method DROP COLUMN {}").format(
            sql.Identifier(source)
        ),
    )


def _fill_provider_from_usage(cr):
    """Last resort for a method the relation table did not link."""
    for table in ("payment_transaction", "payment_token"):
        if not openupgrade.column_exists(cr, table, "payment_method_id"):
            continue
        if not openupgrade.column_exists(cr, table, "provider_id"):
            continue
        openupgrade.logged_query(
            cr,
            sql.SQL(
                """
                UPDATE payment_method AS method
                   SET provider_id = usage.provider_id
                  FROM (
                        SELECT payment_method_id, MIN(provider_id) AS provider_id
                          FROM {table}
                         WHERE provider_id IS NOT NULL
                         GROUP BY payment_method_id
                        HAVING COUNT(DISTINCT provider_id) = 1
                       ) AS usage
                 WHERE method.id = usage.payment_method_id
                   AND method.provider_id IS NULL
                """
            ).format(table=sql.Identifier(table)),
        )


def _delete_unlinked_methods(cr):
    """Drop methods that have no provider and nothing pointing at them.

    20.0 requires ``provider_id``. Each method is created by a provider
    module's data file with that provider set (for example
    ``payment_adyen.payment_method_discover``). The 19.0 catalog rows
    (Cirrus, Discover, JCB, and the rest) are one shared record with no
    provider link. When nothing references them, the row and its xmlid are
    removed so the provider data file can create a new method. A method that
    is still referenced, or that is another method's primary method, is kept.
    """
    filters = []
    for table, column in _payment_method_fks(cr):
        filters.append(
            sql.SQL("AND NOT EXISTS (SELECT 1 FROM {} WHERE {} = method.id)").format(
                sql.Identifier(table),
                sql.Identifier(column),
            )
        )
    if openupgrade.column_exists(cr, "payment_method", "primary_payment_method_id"):
        filters.append(
            sql.SQL(
                """
                AND NOT EXISTS (
                    SELECT 1
                      FROM payment_method AS other
                     WHERE other.primary_payment_method_id = method.id
                )
                """
            )
        )
    extra = sql.SQL(" ").join(filters)
    cr.execute("DROP TABLE IF EXISTS openupgrade_payment_method_drop")
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            CREATE TEMP TABLE openupgrade_payment_method_drop AS
            SELECT method.id
              FROM payment_method AS method
             WHERE method.provider_id IS NULL
               {extra}
            """
        ).format(extra=extra),
    )
    if openupgrade.table_exists(cr, "ir_model_data"):
        openupgrade.logged_query(
            cr,
            """
            DELETE FROM ir_model_data
             WHERE model = 'payment.method'
               AND res_id IN (SELECT id FROM openupgrade_payment_method_drop)
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM payment_method
         WHERE id IN (SELECT id FROM openupgrade_payment_method_drop)
        """,
    )
    cr.execute("DROP TABLE IF EXISTS openupgrade_payment_method_drop")


def _deduplicate_provider_code(cr):
    """``UNIQUE(provider_id, code)`` is new. Keep the lowest id."""
    if not openupgrade.column_exists(cr, "payment_method", "code"):
        return
    cr.execute("DROP TABLE IF EXISTS openupgrade_payment_method_dedup")
    openupgrade.logged_query(
        cr,
        """
        CREATE TEMP TABLE openupgrade_payment_method_dedup AS
        SELECT duplicate.id AS old_id, keeper.id AS new_id
          FROM (
                SELECT id,
                       provider_id,
                       code,
                       ROW_NUMBER() OVER (
                           PARTITION BY provider_id, code
                           ORDER BY id
                       ) AS rn
                  FROM payment_method
                 WHERE provider_id IS NOT NULL
                   AND code IS NOT NULL
               ) AS duplicate
          JOIN (
                SELECT id, provider_id, code
                  FROM (
                        SELECT id,
                               provider_id,
                               code,
                               ROW_NUMBER() OVER (
                                   PARTITION BY provider_id, code
                                   ORDER BY id
                               ) AS rn
                          FROM payment_method
                         WHERE provider_id IS NOT NULL
                           AND code IS NOT NULL
                       ) AS ranked
                 WHERE rn = 1
               ) AS keeper
            ON keeper.provider_id = duplicate.provider_id
           AND keeper.code = duplicate.code
         WHERE duplicate.rn > 1
        """,
    )
    for table, column in _payment_method_fks(cr):
        openupgrade.logged_query(
            cr,
            sql.SQL(
                """
                UPDATE {table} AS target
                   SET {column} = dedup.new_id
                  FROM openupgrade_payment_method_dedup AS dedup
                 WHERE target.{column} = dedup.old_id
                """
            ).format(table=sql.Identifier(table), column=sql.Identifier(column)),
        )
    if openupgrade.column_exists(cr, "payment_method", "primary_payment_method_id"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE payment_method AS method
               SET primary_payment_method_id = dedup.new_id
              FROM openupgrade_payment_method_dedup AS dedup
             WHERE method.primary_payment_method_id = dedup.old_id
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM payment_method
         WHERE id IN (SELECT old_id FROM openupgrade_payment_method_dedup)
        """,
    )
    cr.execute("DROP TABLE IF EXISTS openupgrade_payment_method_dedup")


def _migrate_payment_method_provider(env):
    cr = env.cr
    if not openupgrade.table_exists(cr, "payment_method"):
        return
    openupgrade.add_columns(
        env,
        [("payment.method", "provider_id", "many2one", None, "payment_method")],
    )
    _assign_provider_from_relation(cr)
    _fill_provider_from_usage(cr)
    _deduplicate_provider_code(cr)
    _delete_unlinked_methods(cr)
    cr.execute("SELECT COUNT(*) FROM payment_method WHERE provider_id IS NULL")
    remaining = cr.fetchone()[0]
    if remaining:
        _logger.warning(
            "%s payment.method rows still have no provider_id, so the NOT "
            "NULL constraint cannot be added. Each of them is still "
            "referenced, and no single provider could be taken from the old "
            "relation or from that usage.",
            remaining,
        )


@openupgrade.migrate()
def migrate(env, version):
    _migrate_payment_method_provider(env)
