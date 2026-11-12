# Copyright 2026 Hunki Enterprises BV
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

# pylint: disable=odoo-addons-relative-import
from odoo.addons.openupgrade_scripts.apriori import (
    merged_modules,
    removed_modules,
    renamed_modules,
)

_renamed_xmlids = [
    ("website.default_website", "base.default_website"),
    ("l10n_in.state_in_la", "base.state_in_la"),
    ("base.state_in_or", "base.state_in_od"),
]

_copied_columns = {
    "ir_exports_line": [
        ("id", "sequence", None),
    ],
    "res_company": [
        ("font", None, None),
    ],
}

_merged_xmlids = [
    ("base.state_eg_su", "base.state_eg_gz"),
    ("base.state_eg_hu", "base.state_eg_c"),
]

_renamed_columns = {
    "ir_model_fields": [
        ("index", None),
    ],
    "res_partner_bank": [
        ("acc_number", "account_number"),
        ("acc_holder_name", "holder_name"),
        ("sanitized_acc_number", "sanitized_account_number"),
    ],
    "res_device_log": [
        ("browser", "user_agent"),
    ],
}


def ir_model_access_ir_rule_xmlids(env):
    """
    Postfix all xmlids pointing to ir.rule or ir.model.access with their model name to
    avoid clashes from ir.access records with the same name
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE ir_model_data
        SET name=name || '_' || replace(model, '.', '_')
        WHERE
            model IN ('ir.rule', 'ir.model.access')
        AND
            module NOT IN (
                '__export__', '__custom__', 'studio_customization'
            )
        """,
    )


def ir_actions_client(env):
    """
    Change type of ir.actions.client#params_store to text
    """
    env.cr.execute(
        """
        ALTER TABLE
            ir_act_client
        ALTER COLUMN
            params_store
        SET DATA TYPE
            text
        USING
            CONVERT_FROM(params_store, 'utf8')
        """
    )


def res_company(env):
    """
    Map fonts in res.company#font
    """
    openupgrade.map_values(
        env.cr,
        openupgrade.get_legacy_name("font"),
        "font",
        [("Fira_Mono", "Noto_Sans_Mono")],
        table="res_company",
    )


def res_device_log(env):
    """
    Fill required columns
    """
    for column, value in (
        ("first_activity", "create_date"),
        ("ip_address", "'0.0.0.0'"),
        ("last_activity", "create_date"),
        ("user_agent", "'unknown'"),
        ("user_id", -1),
    ):
        openupgrade.logged_query(
            env.cr, f"UPDATE res_device_log SET {column}={value} WHERE {column} IS NULL"
        )


def _remove_obsolete_modules(env):
    """Mark modules that disappeared from the distribution as ``to remove``.

    Odoo logs ``module <name>: manifest not found`` from ``button_upgrade``
    (that runs before migration scripts) and would leave the row ``to upgrade``.
    ``base`` pre-migration moves the modules listed in ``apriori.removed_modules``
    to ``to remove``. The end of the upgrade then calls ``module_uninstall``,
    which deletes the module's views and assets and sets the state to
    ``uninstalled``. ``theme_common`` (design-themes) is the 20.0 case: the
    snippets library was removed and was not merged into ``website``.
    """
    if not removed_modules:
        return
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE ir_module_module
           SET state = 'to remove'
         WHERE name IN %s
           AND state IN ('installed', 'to upgrade', 'to install')
        """,
        (tuple(removed_modules),),
    )


def ir_actions_server_update_property(env):
    """Pre-create ``ir.actions.server.update_property``.

    The field is a stored computed char. Its compute
    (``_compute_crud_relations`` / ``_get_relation_chain``) does
    ``self.env[self.model_id.model]``. During base initialization that raises
    ``KeyError: 'helpdesk.ticket'`` (and the same for any other model that is
    not part of base) for ``object_write`` actions. NULL is the right value
    for data written before 20.0: nothing stored a property name to update.
    """
    if not openupgrade.table_exists(env.cr, "ir_act_server"):
        return
    openupgrade.add_columns(
        env,
        [
            (
                "ir.actions.server",
                "update_property",
                "char",
                None,
                "ir_act_server",
            )
        ],
    )


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.logged_query(
        env.cr,
        f"""
        CREATE TABLE {
            openupgrade.get_legacy_name("ir_module_module")
        } AS (SELECT name, state FROM ir_module_module);
        """,
    )

    openupgrade.update_module_names(
        env.cr, renamed_modules.items(), environment_namespec=True
    )
    openupgrade.update_module_names(
        env.cr, merged_modules.items(), merge_modules=True, environment_namespec=True
    )
    openupgrade.clean_transient_models(env.cr)
    openupgrade.copy_columns(env.cr, _copied_columns)
    openupgrade.rename_xmlids(env.cr, _renamed_xmlids)
    # merge calls get_many2one_references which expects
    # column ir_model_fields.relation_model_field to exist in v20,
    # but this column will only be created during this upgrade.
    # pretend to be 19 just for this call
    version_info_org = openupgrade.version_info
    openupgrade.version_info = (19,)
    openupgrade.rename_xmlids(env.cr, _merged_xmlids, allow_merge=True)
    openupgrade.version_info = version_info_org
    openupgrade.rename_columns(env.cr, _renamed_columns)
    ir_model_access_ir_rule_xmlids(env)
    ir_actions_client(env)
    res_company(env)
    res_device_log(env)
    openupgrade.set_xml_ids_noupdate_value(
        env, "base", ["module_category_administration"], True
    )
    _remove_obsolete_modules(env)
    ir_actions_server_update_property(env)
