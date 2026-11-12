# Copyright Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import os
import re

from psycopg2 import sql

from odoo import api
from odoo.fields import Domain
from odoo.tools import config

from odoo.addons.base.models.ir_module import IrModuleModule

_LEGACY_MODULE_TABLE = re.compile(r"openupgrade_legacy_\d+_\d+_ir_module_module\Z")


def _keep_legacy_auto_install():
    """Restore installing every uninstalled auto_install module.

    Set ``openupgrade_auto_install_existing = True`` in the Odoo config file, or
    export ``OPENUPGRADE_AUTO_INSTALL_EXISTING=1``.
    """
    raw = os.environ.get("OPENUPGRADE_AUTO_INSTALL_EXISTING")
    if raw is None:
        raw = config.get("openupgrade_auto_install_existing")
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return bool(raw)


def _preexisting_module_names(cr):
    """Modules that must not be auto-installed.

    A row that already exists when ``update_list`` starts was installed or
    deliberately left uninstalled before this call. ``update_list`` only
    creates rows for modules that are new on the addons path.

    ``base`` pre-migration also copies ``ir_module_module`` to
    ``openupgrade_legacy_<version>_ir_module_module``. A later ``update_list``
    (or a row that was deleted and recreated) still has to treat those names
    as pre-existing, otherwise a removed module such as ``iap`` comes back.
    """
    cr.execute("SELECT name FROM ir_module_module")
    names = {row[0] for row in cr.fetchall()}
    cr.execute(
        """
        SELECT tablename
          FROM pg_catalog.pg_tables
         WHERE schemaname = current_schema()
           AND tablename LIKE 'openupgrade_legacy_%_ir_module_module'
        """
    )
    for (table,) in cr.fetchall():
        if not _LEGACY_MODULE_TABLE.fullmatch(table):
            continue
        cr.execute(sql.SQL("SELECT name FROM {}").format(sql.Identifier(table)))
        names.update(row[0] for row in cr.fetchall() if row[0])
    return names


@api.model
def update_list(self):
    """
    Mark auto_install modules as to install if all their dependencies are some kind of
    installed.
    Ignore localization modules that are set to auto_install.

    Only modules whose ``ir.module.module`` row is created by this call are
    installed. A module that was already uninstalled stays uninstalled, even
    when a later Odoo version flips it to ``auto_install`` (``iap`` in 18.0,
    which otherwise pulls ``iap_mail``, ``iap_crm``, ``crm_iap_enrich``,
    ``crm_iap_mine``, ``partner_autocomplete``, ``snailmail`` and
    ``snailmail_account`` back in).
    """
    if _keep_legacy_auto_install():
        preexisting = set()
    else:
        preexisting = _preexisting_module_names(self.env.cr)
    # Resolved at run time: ``IrModuleModule.update_list`` is this function,
    # and ``_original_method`` is assigned on it below.
    result = IrModuleModule.update_list._original_method(self)
    new_auto_install_modules = self.browse([])
    for module in self.env["ir.module.module"].search(
        Domain(
            [
                ("auto_install", "=", True),
                ("state", "=", "uninstalled"),
                ("name", "not like", ("l10n_%")),
            ]
        )
        & Domain.OR(
            [
                Domain("country_ids", "=", False),
                Domain(
                    "country_ids",
                    "in",
                    self.env["res.company"].search([]).country_id.ids,
                ),
            ]
        )
    ):
        if module.name in preexisting:
            continue
        if all(
            state in ("to upgrade", "to install", "installed")
            for state in module.dependencies_id.mapped("state")
        ):
            new_auto_install_modules |= module
    if new_auto_install_modules:
        new_auto_install_modules.button_install()
    return result


def check_external_dependencies(self, module_name, newstate="to install"):
    try:
        IrModuleModule.check_external_dependencies._original_method(
            self, module_name, newstate=newstate
        )
    except AttributeError:  # pylint: disable=except-pass
        # this happens when a module is installed that doesn't exist in the new version
        pass


update_list._original_method = IrModuleModule.update_list
IrModuleModule.update_list = update_list
check_external_dependencies._original_method = (
    IrModuleModule.check_external_dependencies
)
IrModuleModule.check_external_dependencies = check_external_dependencies
