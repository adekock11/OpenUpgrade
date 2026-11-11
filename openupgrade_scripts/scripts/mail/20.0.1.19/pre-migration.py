# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging

from openupgradelib import openupgrade

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


@openupgrade.migrate()
def migrate(env, version):
    _install_mail_tracking(env.cr)
    _blank_views_referencing_removed_fields(env.cr)
    openupgrade.rename_xmlids(env.cr, _renamed_xmlids)
    _preserve_tracking_currency(env.cr)
    _mark_tracking_messages(env.cr)
    _rename_starred_bookmarks(env.cr)
    _migrate_activity_chaining(env.cr)
    _migrate_server_action_notes(env.cr)
