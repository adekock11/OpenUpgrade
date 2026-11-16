# Copyright 2025 Hunki Enterprises BV
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

from odoo.fields import Command


def _ir_actions_act_window_target(env):
    """
    selection value 'inline' was removed, map to 'current'
    """
    openupgrade.logged_query(
        env.cr,
        "UPDATE ir_act_window SET target='current' WHERE target='inline'",
    )


def _quoted_column_names(cr, table):
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s
         ORDER BY ordinal_position
        """,
        (table,),
    )
    return [row[0] for row in cr.fetchall()]


def _copy_relation_rows(cr, table, link_column, old_id, new_id):
    """Copy many2many rows so the duplicate keeps groups and webhook fields."""
    if not openupgrade.table_exists(cr, table):
        return
    columns = _quoted_column_names(cr, table)
    if link_column not in columns:
        return
    column_sql = ", ".join(f'"{column}"' for column in columns)
    select_parts = []
    params = []
    for column in columns:
        if column == link_column:
            select_parts.append("%s")
            params.append(new_id)
        else:
            select_parts.append(f'"{column}"')
    params.append(old_id)
    openupgrade.logged_query(
        cr,
        f"""
        INSERT INTO "{table}" ({column_sql})
        SELECT {", ".join(select_parts)}
          FROM "{table}"
         WHERE "{link_column}" = %s
        """,
        tuple(params),
    )


def _duplicate_server_action(cr, action_id, parent_id, stack):
    """Insert a copy of an ir_act_server row, including inherited columns.

    ir_act_server inherits ir_actions, so one insert copies the action. ``path``
    is cleared because it is unique. Children linked through rel_server_actions
    are copied too: ir.actions.server.child_ids is copied by the ORM.
    """
    if action_id in stack:
        return None
    columns = _quoted_column_names(cr, "ir_act_server")
    if "id" not in columns or "parent_id" not in columns:
        return None
    insert_columns = [column for column in columns if column != "id"]
    column_sql = ", ".join(f'"{column}"' for column in insert_columns)
    select_parts = []
    params = []
    for column in insert_columns:
        if column == "parent_id":
            select_parts.append("%s")
            params.append(parent_id)
        elif column == "path":
            # ir_actions.path is unique; a child copy is not a URL entry point.
            select_parts.append("NULL")
        else:
            select_parts.append(f'"{column}"')
    params.append(action_id)
    openupgrade.logged_query(
        cr,
        f"""
        INSERT INTO ir_act_server ({column_sql})
        SELECT {", ".join(select_parts)}
          FROM ir_act_server
         WHERE id = %s
        RETURNING id
        """,
        tuple(params),
    )
    new_row = cr.fetchone()
    if not new_row:
        return None
    new_id = new_row[0]
    _copy_relation_rows(cr, "ir_act_server_group_rel", "act_id", action_id, new_id)
    _copy_relation_rows(
        cr, "ir_act_server_webhook_field_rel", "server_id", action_id, new_id
    )
    cr.execute(
        """
        SELECT action_id
          FROM rel_server_actions
         WHERE server_id = %s
         ORDER BY action_id
        """,
        (action_id,),
    )
    child_ids = [row[0] for row in cr.fetchall()]
    child_stack = stack | {action_id}
    for child_id in child_ids:
        _duplicate_server_action(cr, child_id, new_id, child_stack)
    return new_id


def _ir_actions_server_child_ids(env):
    """Field changed from m2m to o2m.

    Set parent_id from rel_server_actions. A child with several parents is
    duplicated with SQL, once per extra parent. The ORM copy computes
    ``warning`` and resolves the action model, which is not in the registry
    yet during base's post-migration (KeyError: 'project.task').
    """
    cr = env.cr
    if not openupgrade.table_exists(cr, "rel_server_actions"):
        return
    if not openupgrade.column_exists(cr, "ir_act_server", "parent_id"):
        return
    cr.execute(
        """
        SELECT action_id, array_agg(server_id ORDER BY server_id)
          FROM rel_server_actions
         GROUP BY action_id
        HAVING COUNT(*) > 1
        """
    )
    multi_parent = cr.fetchall()
    openupgrade.logged_query(
        cr,
        """
        UPDATE ir_act_server AS child
           SET parent_id = rel.parent_id
          FROM (
                SELECT action_id,
                       (array_agg(server_id ORDER BY server_id))[1] AS parent_id
                  FROM rel_server_actions
                 GROUP BY action_id
               ) AS rel
         WHERE child.id = rel.action_id
           AND child.parent_id IS NULL
        """,
    )
    for action_id, parent_ids in multi_parent:
        for parent_id in parent_ids[1:]:
            _duplicate_server_action(cr, action_id, parent_id, frozenset())


def _ir_actions_server_html_value(env):
    """
    For evaluation_type 'value' and update_field_id.ttype == 'html',
    new field html_value is used
    """
    for action in env["ir.actions.server"].search(
        [
            ("state", "=", "object_write"),
            ("evaluation_type", "=", "value"),
            ("update_field_id.ttype", "=", "html"),
        ]
    ):
        action.write({"html_value": action.value})


def _ir_filters_user_ids(env):
    """
    m2o user_id has been transformed to m2m user_ids
    """
    openupgrade.m2o_to_x2m(
        env.cr, env["ir.filters"], env["ir.filters"]._table, "user_ids", "user_id"
    )


def _res_lang(env):
    """
    Char fields date_format, grouping and time_format have been dumbed down to
    selection fields. Keep their original value in a legacy column, and map existing
    values not in the selection to the default value
    """
    ResLang = env["res.lang"]
    for field_name in ("date_format", "time_format", "grouping"):
        field = ResLang._fields[field_name]
        openupgrade.copy_columns(env.cr, {"res_lang": [(field_name, None, None)]})
        openupgrade.logged_query(
            env.cr,
            f"UPDATE res_lang SET {field_name}=%(default)s "
            f"WHERE {field_name} NOT IN %(selection)s",
            {
                "default": field.default(ResLang),
                "selection": tuple(
                    value for value, _string in field._description_selection(env)
                ),
            },
        )


def _init_default_user_group(env):
    """
    Assign all groups of default_user to implied_ids of default_user_group
    """
    default_user = env.ref("base.default_user", raise_if_not_found=False)
    if not default_user:
        return
    env.ref("base.default_user_group").write(
        {
            "implied_ids": [Command.set(default_user.group_ids.ids)],
        }
    )


def _migrate_partner_mobile(env):
    openupgrade.copy_columns(env.cr, {"res_partner": [("phone", None, None)]})
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE res_partner
        SET phone = CONCAT(
            COALESCE(phone, ''),
            CASE WHEN COALESCE(phone, '') != '' THEN ' // ' ELSE '' END,
            mobile
        )
        WHERE COALESCE(mobile, '') != ''
        AND COALESCE(phone, '') != COALESCE(mobile, '')
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.load_data(
        env,
        "base",
        "19.0.1.3/noupdate_changes.xml",
        xml_transformation_filename="19.0.1.3/noupdate_changes-transformation.xml",
    )
    _init_default_user_group(env)
    openupgrade.delete_records_safely_by_xml_id(
        env,
        ["base.ir_filters_delete_own_rule", "base.default_user"],
    )
    _ir_actions_act_window_target(env)
    _ir_actions_server_child_ids(env)
    _ir_actions_server_html_value(env)
    _ir_filters_user_ids(env)
    _res_lang(env)
    _migrate_partner_mobile(env)
