# Copyright 2026 Hunki Enterprises BV
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade, openupgrade_200
from psycopg2.extras import execute_values

from odoo.tools import format_amount, formatLang, is_html_empty

_logger = logging.getLogger(__name__)

TRACKING_BODY_BATCH = 2000


def _tracking_display_value(thread, field_type, tracking, prefix, field_info):
    """Format one side of a stored tracking value as 20.0 posts it.

    Mirrors ``mail.track.mixin._create_mail_tracking_values``, reading the
    stored columns instead of live values.
    """
    if field_type in ("integer", "float"):
        value = tracking[f"{prefix}_value_{field_type}"]
        return formatLang(
            thread.env,
            value or 0,
            rounding_unit="units" if field_type == "integer" else "decimals",
        )
    if field_type == "monetary":
        value = tracking[f"{prefix}_value_float"] or 0
        currency = (
            thread.env["res.currency"].browse(field_info.get("currency_id")).exists()
        )
        if currency:
            return format_amount(thread.env, value, currency)
        return formatLang(thread.env, value)
    if field_type == "datetime":
        value = tracking[f"{prefix}_value_datetime"]
        return thread._format_tracking_datetime(value) if value else "None"
    if field_type == "date":
        value = tracking[f"{prefix}_value_datetime"]
        return thread._format_tracking_date(value.date()) if value else "None"
    if field_type == "boolean":
        return (
            thread.env._("Yes")
            if tracking[f"{prefix}_value_integer"]
            else thread.env._("No")
        )
    if field_type == "text":
        return tracking[f"{prefix}_value_text"] or "None"
    # char, selection, many2one, many2many, one2many, tags and unknown types
    # all keep their display value in the char column.
    return (
        tracking[f"{prefix}_value_char"] or tracking[f"{prefix}_value_text"] or "None"
    )


def _tracking_values_for_render(thread, trackings, fields_by_id):
    values = []
    companies = thread.env["res.company"].sudo()
    for tracking in trackings:
        field_info = tracking["field_info"] or {}
        field = fields_by_id.get(tracking["field_id"])
        field_type = (field and field.ttype) or field_info.get("type") or "char"
        label = (
            (field and field.field_description)
            or field_info.get("desc")
            or field_info.get("name")
            or ""
        )
        value = {
            "field_label": label,
            "old_value": _tracking_display_value(
                thread, field_type, tracking, "old", field_info
            ),
            "new_value": _tracking_display_value(
                thread, field_type, tracking, "new", field_info
            ),
        }
        if field_info.get("company_id"):
            company = companies.browse(field_info["company_id"]).exists()
            if company:
                value["company_name"] = company.name
        values.append(value)
    return values


def _backfill_tracking_bodies(env, batch_size=TRACKING_BODY_BATCH):
    """Write the tracking summary into the body of older tracking messages.

    20.0 renders tracking values into ``mail.message.body`` when the message
    is posted (``mail.thread._message_compute_body_with_trackings``) and the
    chatter only shows the body. Before 20.0 the body stayed empty and the
    web client drew ``mail.tracking.value`` itself, so after migration those
    messages show "This message has been removed".

    Rebuild the same HTML from the stored tracking values. Bodies that are
    empty (``is_html_empty``) are replaced; a real body gets the tracking
    appended. Messages whose body already contains the tracking arrow (posted
    by 20.0 code) are skipped, so the step can run again safely. Bodies are
    written with SQL: nothing is posted, sent or notified, and ``write_date``
    is unchanged. The author's language and time zone are used, falling back
    to the administrator's, like a user who posted the change.
    """
    cr = env.cr
    if not openupgrade.table_exists(cr, "mail_tracking_value"):
        return 0
    admin = env.ref("base.user_admin", raise_if_not_found=False) or env.user
    default_lang = admin.lang or "en_US"
    default_tz = admin.tz or "UTC"
    langs = {code for code, _name in env["res.lang"].get_installed()}
    cr.execute(
        """
        SELECT DISTINCT message.id
          FROM mail_message AS message
          JOIN mail_tracking_value AS tracking
            ON tracking.mail_message_id = message.id
         WHERE COALESCE(message.body, '') NOT LIKE %s
         ORDER BY message.id
        """,
        ("%\u2192%",),
    )
    message_ids = [row[0] for row in cr.fetchall()]
    total = 0
    for start in range(0, len(message_ids), batch_size):
        chunk = message_ids[start : start + batch_size]
        cr.execute(
            """
            SELECT message.id, message.body, partner.lang, partner.tz
              FROM mail_message AS message
              LEFT JOIN res_partner AS partner ON partner.id = message.author_id
             WHERE message.id IN %s
            """,
            (tuple(chunk),),
        )
        messages = cr.dictfetchall()
        cr.execute(
            """
            SELECT id, mail_message_id, field_id, field_info,
                   old_value_integer, new_value_integer,
                   old_value_float, new_value_float,
                   old_value_char, new_value_char,
                   old_value_text, new_value_text,
                   old_value_datetime, new_value_datetime
              FROM mail_tracking_value
             WHERE mail_message_id IN %s
             ORDER BY mail_message_id, id
            """,
            (tuple(chunk),),
        )
        trackings_by_message = {}
        field_ids = set()
        for tracking in cr.dictfetchall():
            trackings_by_message.setdefault(tracking["mail_message_id"], []).append(
                tracking
            )
            if tracking["field_id"]:
                field_ids.add(tracking["field_id"])
        updates = []
        threads = {}
        fields_cache = {}
        for message in messages:
            lang = message["lang"] if message["lang"] in langs else default_lang
            tz = message["tz"] or default_tz
            key = (lang, tz)
            if key not in threads:
                threads[key] = env["mail.thread"].with_context(lang=lang, tz=tz)
                fields_cache[key] = {
                    field.id: field
                    for field in env["ir.model.fields"]
                    .with_context(lang=lang)
                    .sudo()
                    .browse(field_ids)
                    .exists()
                }
            thread = threads[key]
            trackings = trackings_by_message.get(message["id"])
            if not trackings:
                continue
            values = _tracking_values_for_render(thread, trackings, fields_cache[key])
            body = message["body"]
            if is_html_empty(body):
                body = ""
            # Same call as message_post: values in creation order, the
            # method reverses them like the ORM's 'id DESC' read.
            new_body = thread._message_compute_body_with_trackings(body, values)
            updates.append((message["id"], str(new_body)))
        if updates:
            execute_values(
                cr._obj,
                """
                UPDATE mail_message AS message
                   SET body = data.body
                  FROM (VALUES %s) AS data (id, body)
                 WHERE message.id = data.id
                """,
                updates,
                page_size=1000,
            )
            total += len(updates)
        _logger.info(
            "Tracking bodies: %s/%s messages done",
            min(start + batch_size, len(message_ids)),
            len(message_ids),
        )
    env["mail.message"].invalidate_model(["body"])
    _logger.info("Wrote the tracking summary in the body of %s messages", total)
    return total


@openupgrade.migrate()
def migrate(env, version):
    openupgrade_200.migrate_qweb_fields(env, "mail.template", "body_html")
    _backfill_tracking_bodies(env)
