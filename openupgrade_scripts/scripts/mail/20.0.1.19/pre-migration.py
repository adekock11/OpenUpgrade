# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging

from openupgradelib import openupgrade
from psycopg2 import sql
from psycopg2.errors import UniqueViolation

_logger = logging.getLogger(__name__)

_renamed_xmlids = [
    (
        "mail.action_view_mail_tracking_value",
        "mail_tracking.action_view_mail_tracking_value",
    ),
    (
        "mail.menu_mail_tracking_value",
        "mail_tracking.menu_mail_tracking_value",
    ),
    (
        "mail.view_mail_tracking_value_form",
        "mail_tracking.view_mail_tracking_value_form",
    ),
    (
        "mail.view_mail_tracking_value_tree",
        "mail_tracking.view_mail_tracking_value_tree",
    ),
    (
        "mail.model_mail_tracking_value",
        "mail_tracking.model_mail_tracking_value",
    ),
]


def _ensure_column(cr, table, column, column_type):
    if openupgrade.column_exists(cr, table, column):
        return
    queries = {
        ("mail_activity_type", "suggested_next_type_id", "int4"): (
            "ALTER TABLE mail_activity_type ADD COLUMN suggested_next_type_id int4"
        ),
        ("ir_act_server", "log_note_note", "jsonb"): (
            "ALTER TABLE ir_act_server ADD COLUMN log_note_note jsonb"
        ),
    }
    openupgrade.logged_query(cr, queries[(table, column, column_type)])


def _schedule_new_module(cr, name):
    """Mark a module introduced in 20.0 to install during this upgrade.

    ``ir.module.module.update_list()`` has already run, so rows for modules
    that are on the addons path exist. Setting ``to install`` here is picked
    up by the module-loading loop before ``ir.model.data._process_end``, which
    is what keeps moved records from being deleted as leftovers of ``mail``.
    """
    openupgrade.logged_query(
        cr,
        """
        UPDATE ir_module_module
           SET state = 'to install'
         WHERE name = %s
           AND state = 'uninstalled'
        """,
        (name,),
    )
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", (name,))
    row = cr.fetchone()
    if not row:
        _logger.error(
            "Module %s is not in ir_module_module. It must be on the addons "
            "path or data that moved into it will not be loaded.",
            name,
        )
    return row and row[0]


def _install_mail_tracking(cr):
    """Discuss tracking was split out of mail and is not auto_install.

    The model name and table stay ``mail.tracking.value`` /
    ``mail_tracking_value``. Installing the new module reuses that table.
    The mass-mailing and SMS glue modules are ``auto_install``, but
    ``update_list()`` already ran before this script could mark
    ``mail_tracking`` to install, so schedule them explicitly when their
    other dependency is already installed.
    """
    state = _schedule_new_module(cr, "mail_tracking")
    if state not in ("to install", "to upgrade", "installed"):
        return
    cr.execute(
        """
        SELECT name FROM ir_module_module
         WHERE name IN ('mass_mailing', 'sms')
           AND state IN ('installed', 'to upgrade', 'to install')
        """
    )
    installed = {row[0] for row in cr.fetchall()}
    if "mass_mailing" in installed:
        _schedule_new_module(cr, "mail_tracking_mass_mailing")
    if "sms" in installed:
        _schedule_new_module(cr, "mail_tracking_sms")


def _preserve_tracking_currency(cr):
    """19.0 stored the currency of a monetary tracking on ``currency_id``.

    20.0 drops that column and keeps the currency id inside ``field_info``
    (see ``mail.track.mixin``). Copy it before the column is removed, when
    ``mail_tracking`` initializes the model.
    """
    if not openupgrade.column_exists(cr, "mail_tracking_value", "currency_id"):
        return
    if not openupgrade.column_exists(cr, "mail_tracking_value", "field_info"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE mail_tracking_value
           SET field_info = COALESCE(field_info::jsonb, '{}'::jsonb)
               || jsonb_build_object('currency_id', currency_id)
         WHERE currency_id IS NOT NULL
           AND (
                field_info IS NULL
                OR NOT (COALESCE(field_info::jsonb, '{}'::jsonb) ? 'currency_id')
           )
        """,
    )


def _mark_tracking_messages(cr):
    """20.0 stores field-change logs as ``message_type = 'tracking'``.

    19.0 stored them as ``notification`` messages that have tracking values.
    The Discuss "changes" search only matches ``tracking``. Comments that
    also carry tracking values are left as comments.
    """
    if not openupgrade.table_exists(cr, "mail_tracking_value"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE mail_message AS message
           SET message_type = 'tracking'
         WHERE message.message_type = 'notification'
           AND EXISTS (
                SELECT 1
                  FROM mail_tracking_value AS tracking
                 WHERE tracking.mail_message_id = message.id
           )
        """,
    )


def _rename_starred_bookmarks(cr):
    """Starred messages were renamed to bookmarks. Same columns, new table."""
    old = "mail_message_res_partner_starred_rel"
    new = "mail_message_res_partner_bookmarked_rel"
    if openupgrade.table_exists(cr, old) and not openupgrade.table_exists(cr, new):
        openupgrade.rename_tables(cr, [(old, new)])


def _migrate_activity_chaining(cr):
    """Suggest-next went from a many2many (or a triggered many2one) to one
    many2one, ``suggested_next_type_id``.

    ``previous_type_ids`` still uses ``mail_activity_rel``, so every old
    suggestion stays visible as a preceding activity. 20.0 can only suggest
    a single next type: a ``trigger`` chain wins, otherwise the lowest
    ``recommended_id`` is kept. Automatic triggering no longer exists; the
    link is preserved as a suggestion.
    """
    if not openupgrade.table_exists(cr, "mail_activity_type"):
        return
    _ensure_column(cr, "mail_activity_type", "suggested_next_type_id", "int4")
    if not openupgrade.column_exists(cr, "mail_activity_type", "chaining_type"):
        return
    if openupgrade.column_exists(cr, "mail_activity_type", "triggered_next_type_id"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE mail_activity_type
               SET suggested_next_type_id = triggered_next_type_id
             WHERE chaining_type = 'trigger'
               AND triggered_next_type_id IS NOT NULL
               AND suggested_next_type_id IS NULL
            """,
        )
    if openupgrade.table_exists(cr, "mail_activity_rel"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE mail_activity_type AS activity_type
               SET suggested_next_type_id = suggestion.recommended_id
              FROM (
                    SELECT DISTINCT ON (activity_id)
                           activity_id,
                           recommended_id
                      FROM mail_activity_rel
                     ORDER BY activity_id, recommended_id
                   ) AS suggestion
             WHERE activity_type.id = suggestion.activity_id
               AND activity_type.chaining_type IS DISTINCT FROM 'trigger'
               AND activity_type.suggested_next_type_id IS NULL
            """,
        )
        cr.execute(
            """
            SELECT COUNT(*)
              FROM (
                    SELECT activity_id
                      FROM mail_activity_rel
                     GROUP BY activity_id
                    HAVING COUNT(*) > 1
                   ) AS extra
            """
        )
        extra = cr.fetchone()[0]
        if extra:
            _logger.info(
                "%s activity types suggested more than one next activity. "
                "20.0 keeps a single suggested_next_type_id (lowest id); "
                "the other links remain on previous_type_ids.",
                extra,
            )


# Fields removed in 20.0 that 19.0 standard views still reference. ir.cron's form
# is validated before mail replaces the server-action view, so the old arch has
# to be neutralized first. Only views that name one of these fields are touched.
# Standard mail views are reloaded from XML afterwards. A custom view that still
# names a removed field is reduced to an empty arch so the upgrade can continue;
# that customization has to be reapplied.
_OBSOLETE_VIEW_FIELDS = (
    "mail_post_method",
    "chaining_type",
    "triggered_next_type_id",
    "suggested_next_type_ids",
    "previous_activity_type_id",
    "recommended_activity_type_id",
    "has_recommended_activities",
    "custom_channel_name",
    "fetched_message_id",
    "starred_partner_ids",
)


def _blank_views_referencing_removed_fields(cr):
    # arch_db::text escapes quotes, so match the field name itself.
    pattern = "|".join(_OBSOLETE_VIEW_FIELDS)
    cr.execute(
        """
        SELECT id, inherit_id IS NOT NULL, COALESCE(type, 'form'), arch_db
          FROM ir_ui_view
         WHERE arch_db::text ~ %s
        """,
        (pattern,),
    )
    rows = cr.fetchall()
    for view_id, is_inherit, view_type, arch_db in rows:
        if is_inherit:
            empty = "<data/>"
        elif view_type == "list":
            empty = "<list/>"
        elif view_type == "search":
            empty = "<search/>"
        elif view_type == "kanban":
            empty = "<kanban/>"
        else:
            empty = "<form/>"
        if isinstance(arch_db, str):
            arch_db = json.loads(arch_db)
        new_arch = {lang: empty for lang in (arch_db or {"en_US": empty})}
        openupgrade.logged_query(
            cr,
            "UPDATE ir_ui_view SET arch_db = %s::jsonb WHERE id = %s",
            (json.dumps(new_arch), view_id),
        )
    if rows:
        _logger.info(
            "Neutralized %s views that referenced fields removed from mail.",
            len(rows),
        )


def _migrate_server_action_notes(cr):
    """``mail_post_method = note`` becomes the ``log_note`` server action.

    19.0 rendered ``template_id`` as an internal note. 20.0 log notes post
    ``log_note_note`` and do not render a template, so the template body
    (including translations) is copied into that field. ``comment`` stays
    ``mail_post``. ``email`` also stays ``mail_post``: on a mail.thread model
    20.0 always posts the template as a comment, there is no email-only mode.
    """
    if not openupgrade.column_exists(cr, "ir_act_server", "mail_post_method"):
        return
    _ensure_column(cr, "ir_act_server", "log_note_note", "jsonb")
    if openupgrade.column_exists(cr, "mail_template", "body_html"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE ir_act_server AS action
               SET state = 'log_note',
                   log_note_note = template.body_html::jsonb
              FROM mail_template AS template
             WHERE action.template_id = template.id
               AND action.state = 'mail_post'
               AND action.mail_post_method = 'note'
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        UPDATE ir_act_server
           SET state = 'log_note'
         WHERE state = 'mail_post'
           AND mail_post_method = 'note'
        """,
    )


def _discuss_channel_fks(cr):
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
           AND dst.relname = 'discuss_channel'
           AND ns.nspname = current_schema()
           AND array_length(con.conkey, 1) = 1
        """
    )
    return cr.fetchall()


def _fill_member_indices(cr):
    """Store ``discuss.channel.member_indices`` in Odoo's format.

    ``DiscussChannel._member_indices`` joins sorted partner ids as ``p<id>``
    and then sorted guest ids as ``g<id>``, comma-separated. Non-chats stay
    NULL (``member_indices_channel_check``). A chat with no partner and no
    guest cannot satisfy ``member_indices_chat_check`` (non-empty). Those
    rows become group conversations so their messages are kept and the chat
    constraints do not apply.
    """
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel AS channel
           SET member_indices = tokens.indices
          FROM (
                SELECT channel_id,
                       string_agg(
                           token, ',' ORDER BY sort_group, sort_id
                       ) AS indices
                  FROM (
                        SELECT channel_id,
                               'p' || partner_id::text AS token,
                               0 AS sort_group,
                               partner_id AS sort_id
                          FROM discuss_channel_member
                         WHERE partner_id IS NOT NULL
                         GROUP BY channel_id, partner_id
                        UNION ALL
                        SELECT channel_id,
                               'g' || guest_id::text AS token,
                               1 AS sort_group,
                               guest_id AS sort_id
                          FROM discuss_channel_member
                         WHERE guest_id IS NOT NULL
                         GROUP BY channel_id, guest_id
                       ) AS member
                 GROUP BY channel_id
               ) AS tokens
         WHERE channel.id = tokens.channel_id
           AND channel.channel_type = 'chat'
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel
           SET member_indices = NULL
         WHERE channel_type IS DISTINCT FROM 'chat'
        """,
    )
    # A chat with no partner and no guest cannot satisfy the chat check.
    # Become a group and clear fields that only a channel may set, so the
    # group_public_id / is_readonly checks do not fire. Messages stay put.
    assignments = [
        sql.SQL("channel_type = 'group'"),
        sql.SQL("member_indices = NULL"),
    ]
    if openupgrade.column_exists(cr, "discuss_channel", "group_public_id"):
        assignments.append(sql.SQL("group_public_id = NULL"))
    if openupgrade.column_exists(cr, "discuss_channel", "is_readonly"):
        assignments.append(sql.SQL("is_readonly = FALSE"))
    openupgrade.logged_query(
        cr,
        sql.SQL(
            """
            UPDATE discuss_channel
               SET {}
             WHERE channel_type = 'chat'
               AND (member_indices IS NULL OR btrim(member_indices) = '')
            """
        ).format(sql.SQL(", ").join(assignments)),
    )


def _member_identity_fks(cr):
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
           AND dst.relname = 'discuss_channel_member'
           AND ns.nspname = current_schema()
           AND array_length(con.conkey, 1) = 1
        """
    )
    return cr.fetchall()


def _merge_member_rows(cr):
    """Keep one member per (partner, guest) on the surviving chat.

    NULL partner and NULL guest are a real identity: two guest-only members
    stay distinct, and a row with both NULL does not swallow a partner row.
    PostgreSQL treats those NULLs as equal for DISTINCT ON, which is what we
    want for the empty identity and not for mixed ones.

    The survivor is the member already on the keeper channel when there is
    one, otherwise the lowest id. ``seen_message_id`` (and ``fetched_message_id``
    when that column still exists) becomes the greatest id in the group, so
    several duplicate rows cannot make the UPDATE pick an arbitrary value.
    """
    openupgrade.logged_query(
        cr,
        """
        DROP TABLE IF EXISTS openupgrade_member_survivor;
        """,
    )
    # logged_query executes one statement. Create the map separately.
    openupgrade.logged_query(
        cr,
        """
        CREATE TEMP TABLE openupgrade_member_survivor AS
        SELECT DISTINCT ON (pair.keeper_id, member.partner_id, member.guest_id)
               member.id AS survivor_id,
               pair.keeper_id,
               member.partner_id,
               member.guest_id
          FROM discuss_channel_member AS member
          JOIN openupgrade_chat_duplicate AS pair
            ON pair.duplicate_id = member.channel_id
            OR pair.keeper_id = member.channel_id
         ORDER BY pair.keeper_id,
                  member.partner_id,
                  member.guest_id,
                  (member.channel_id = pair.keeper_id) DESC,
                  member.id
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel_member AS survivor
           SET seen_message_id = grouped.max_seen
          FROM (
                SELECT map.survivor_id,
                       MAX(member.seen_message_id) AS max_seen
                  FROM openupgrade_member_survivor AS map
                  JOIN discuss_channel_member AS member
                    ON member.partner_id IS NOT DISTINCT FROM map.partner_id
                   AND member.guest_id IS NOT DISTINCT FROM map.guest_id
                   AND (
                        member.channel_id = map.keeper_id
                        OR member.channel_id IN (
                            SELECT duplicate_id
                              FROM openupgrade_chat_duplicate
                             WHERE keeper_id = map.keeper_id
                        )
                   )
                 GROUP BY map.survivor_id
               ) AS grouped
         WHERE survivor.id = grouped.survivor_id
           AND grouped.max_seen IS NOT NULL
           AND (
                survivor.seen_message_id IS NULL
                OR grouped.max_seen > survivor.seen_message_id
           )
        """,
    )
    if openupgrade.column_exists(cr, "discuss_channel_member", "fetched_message_id"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE discuss_channel_member AS survivor
               SET fetched_message_id = grouped.max_fetched
              FROM (
                    SELECT map.survivor_id,
                           MAX(member.fetched_message_id) AS max_fetched
                      FROM openupgrade_member_survivor AS map
                      JOIN discuss_channel_member AS member
                        ON member.partner_id IS NOT DISTINCT FROM map.partner_id
                       AND member.guest_id IS NOT DISTINCT FROM map.guest_id
                       AND (
                            member.channel_id = map.keeper_id
                            OR member.channel_id IN (
                                SELECT duplicate_id
                                  FROM openupgrade_chat_duplicate
                                 WHERE keeper_id = map.keeper_id
                            )
                       )
                     GROUP BY map.survivor_id
                   ) AS grouped
             WHERE survivor.id = grouped.survivor_id
               AND grouped.max_fetched IS NOT NULL
               AND (
                    survivor.fetched_message_id IS NULL
                    OR grouped.max_fetched > survivor.fetched_message_id
               )
            """,
        )
    for table, column in _member_identity_fks(cr):
        try:
            with cr.savepoint():
                openupgrade.logged_query(
                    cr,
                    sql.SQL(
                        """
                        UPDATE {table} AS target
                           SET {column} = map.survivor_id
                          FROM discuss_channel_member AS member
                          JOIN openupgrade_member_survivor AS map
                            ON member.partner_id IS NOT DISTINCT FROM map.partner_id
                           AND member.guest_id IS NOT DISTINCT FROM map.guest_id
                           AND member.id <> map.survivor_id
                           AND (
                                member.channel_id = map.keeper_id
                                OR member.channel_id IN (
                                    SELECT duplicate_id
                                      FROM openupgrade_chat_duplicate
                                     WHERE keeper_id = map.keeper_id
                                )
                           )
                         WHERE target.{column} = member.id
                        """
                    ).format(
                        table=sql.Identifier(table),
                        column=sql.Identifier(column),
                    ),
                )
        except UniqueViolation:
            _logger.warning(
                "Could not re-point %s.%s onto the kept channel member.",
                table,
                column,
            )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM discuss_channel_member AS member
         USING openupgrade_member_survivor AS map
         WHERE member.partner_id IS NOT DISTINCT FROM map.partner_id
           AND member.guest_id IS NOT DISTINCT FROM map.guest_id
           AND member.id <> map.survivor_id
           AND (
                member.channel_id = map.keeper_id
                OR member.channel_id IN (
                    SELECT duplicate_id
                      FROM openupgrade_chat_duplicate
                     WHERE keeper_id = map.keeper_id
                )
           )
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE discuss_channel_member AS member
           SET channel_id = map.keeper_id
          FROM openupgrade_member_survivor AS map
         WHERE member.id = map.survivor_id
           AND member.channel_id <> map.keeper_id
        """,
    )
    cr.execute("DROP TABLE IF EXISTS openupgrade_member_survivor")


def _merge_followers(cr):
    if not openupgrade.table_exists(cr, "mail_followers"):
        return
    subtype = "mail_followers_mail_message_subtype_rel"
    if openupgrade.table_exists(cr, subtype):
        openupgrade.logged_query(
            cr,
            """
            INSERT INTO mail_followers_mail_message_subtype_rel (
                mail_followers_id, mail_message_subtype_id
            )
            SELECT keeper.id, rel.mail_message_subtype_id
              FROM mail_followers AS dup
              JOIN openupgrade_chat_duplicate AS pair
                ON pair.duplicate_id = dup.res_id
              JOIN mail_followers AS keeper
                ON keeper.res_model = 'discuss.channel'
               AND keeper.res_id = pair.keeper_id
               AND keeper.partner_id = dup.partner_id
               AND dup.partner_id IS NOT NULL
              JOIN mail_followers_mail_message_subtype_rel AS rel
                ON rel.mail_followers_id = dup.id
             WHERE dup.res_model = 'discuss.channel'
               AND NOT EXISTS (
                    SELECT 1
                      FROM mail_followers_mail_message_subtype_rel AS existing
                     WHERE existing.mail_followers_id = keeper.id
                       AND existing.mail_message_subtype_id =
                           rel.mail_message_subtype_id
               )
            """,
        )
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM mail_followers AS dup
         USING openupgrade_chat_duplicate AS pair,
               mail_followers AS keeper
         WHERE dup.res_model = 'discuss.channel'
           AND dup.res_id = pair.duplicate_id
           AND keeper.res_model = 'discuss.channel'
           AND keeper.res_id = pair.keeper_id
           AND keeper.partner_id = dup.partner_id
           AND dup.partner_id IS NOT NULL
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        UPDATE mail_followers AS follower
           SET res_id = pair.keeper_id
          FROM openupgrade_chat_duplicate AS pair
         WHERE follower.res_model = 'discuss.channel'
           AND follower.res_id = pair.duplicate_id
        """,
    )


def _repoint_channel_fks(cr):
    for table, column in _discuss_channel_fks(cr):
        if table == "discuss_channel_member":
            continue
        if table == "discuss_channel":
            openupgrade.logged_query(
                cr,
                sql.SQL(
                    """
                    UPDATE discuss_channel AS channel
                       SET {column} = NULL
                      FROM openupgrade_chat_duplicate AS pair
                     WHERE channel.id = pair.keeper_id
                       AND channel.{column} = pair.duplicate_id
                    """
                ).format(column=sql.Identifier(column)),
            )
        try:
            with cr.savepoint():
                openupgrade.logged_query(
                    cr,
                    sql.SQL(
                        """
                        UPDATE {table} AS target
                           SET {column} = pair.keeper_id
                          FROM openupgrade_chat_duplicate AS pair
                         WHERE target.{column} = pair.duplicate_id
                        """
                    ).format(
                        table=sql.Identifier(table),
                        column=sql.Identifier(column),
                    ),
                )
        except UniqueViolation:
            _logger.warning(
                "Could not re-point %s.%s while merging duplicate chats.",
                table,
                column,
            )


def _merge_duplicate_chats(env):
    """Collapse DM chats that share a member set.

    Older versions allowed several chats between the same members. 20.0 adds
    the partial unique index ``discuss_channel_member_indices_unique`` on
    chats, which raises ``duplicate key value violates unique constraint``.
    The oldest chat (``create_date``, then ``id``) is kept. Messages
    (``model = discuss.channel``), members, followers and attachments move
    onto it. The discuss.channel message count is unchanged.
    """
    cr = env.cr
    if not openupgrade.table_exists(cr, "discuss_channel"):
        return
    if not openupgrade.table_exists(cr, "discuss_channel_member"):
        return
    before = None
    if openupgrade.table_exists(cr, "mail_message"):
        cr.execute("SELECT COUNT(*) FROM mail_message WHERE model = 'discuss.channel'")
        before = cr.fetchone()[0]
    openupgrade.add_columns(
        env,
        [("discuss.channel", "member_indices", "char", None, "discuss_channel")],
    )
    _fill_member_indices(cr)
    cr.execute("DROP TABLE IF EXISTS openupgrade_chat_duplicate")
    openupgrade.logged_query(
        cr,
        """
        CREATE TEMP TABLE openupgrade_chat_duplicate (
            duplicate_id INTEGER PRIMARY KEY,
            keeper_id INTEGER NOT NULL
        )
        """,
    )
    openupgrade.logged_query(
        cr,
        """
        INSERT INTO openupgrade_chat_duplicate (duplicate_id, keeper_id)
        WITH ranked AS (
            SELECT id,
                   member_indices,
                   ROW_NUMBER() OVER (
                       PARTITION BY member_indices
                       ORDER BY create_date NULLS LAST, id
                   ) AS rn
              FROM discuss_channel
             WHERE channel_type = 'chat'
               AND member_indices IS NOT NULL
               AND btrim(member_indices) <> ''
        )
        SELECT duplicate.id, keeper.id
          FROM ranked AS duplicate
          JOIN ranked AS keeper
            ON keeper.member_indices = duplicate.member_indices
           AND keeper.rn = 1
         WHERE duplicate.rn > 1
        """,
    )
    cr.execute("SELECT COUNT(*) FROM openupgrade_chat_duplicate")
    duplicate_count = cr.fetchone()[0]
    if duplicate_count:
        _logger.info(
            "Merging %s duplicate discuss.channel chats into the oldest chat.",
            duplicate_count,
        )
    if openupgrade.table_exists(cr, "mail_message"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE mail_message AS message
               SET res_id = pair.keeper_id
              FROM openupgrade_chat_duplicate AS pair
             WHERE message.model = 'discuss.channel'
               AND message.res_id = pair.duplicate_id
            """,
        )
    _merge_member_rows(cr)
    _merge_followers(cr)
    if openupgrade.table_exists(cr, "ir_attachment"):
        openupgrade.logged_query(
            cr,
            """
            UPDATE ir_attachment AS attachment
               SET res_id = pair.keeper_id
              FROM openupgrade_chat_duplicate AS pair
             WHERE attachment.res_model = 'discuss.channel'
               AND attachment.res_id = pair.duplicate_id
            """,
        )
    _repoint_channel_fks(cr)
    openupgrade.logged_query(
        cr,
        """
        DELETE FROM discuss_channel
         WHERE id IN (SELECT duplicate_id FROM openupgrade_chat_duplicate)
        """,
    )
    after = before
    if before is not None:
        cr.execute("SELECT COUNT(*) FROM mail_message WHERE model = 'discuss.channel'")
        after = cr.fetchone()[0]
    cr.execute("DROP TABLE IF EXISTS openupgrade_chat_duplicate")
    if before is not None and before != after:
        raise RuntimeError(
            "Merging duplicate discuss.channel chats changed the message "
            f"count from {before} to {after}."
        )
    _logger.info(
        "discuss.channel chats now have member_indices. Message count is %s.",
        after,
    )


@openupgrade.migrate()
def migrate(env, version):
    _merge_duplicate_chats(env)
    _install_mail_tracking(env.cr)
    _blank_views_referencing_removed_fields(env.cr)
    openupgrade.rename_xmlids(env.cr, _renamed_xmlids)
    _preserve_tracking_currency(env.cr)
    _mark_tracking_messages(env.cr)
    _rename_starred_bookmarks(env.cr)
    _migrate_activity_chaining(env.cr)
    _migrate_server_action_notes(env.cr)
