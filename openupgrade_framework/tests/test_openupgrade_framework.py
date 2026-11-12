import os

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tools.misc import mute_logger

from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG


class TestOpenupgradeFramework(TransactionCase):
    def test_01_delete_undeletable_record(self):
        """
        Test that Odoo doesn't crash when deleting records that can't be deleted
        during module upgrade
        """
        with (
            mute_logger("odoo.sql_db"),
            self.assertLogs(
                "odoo.addons.openupgrade_framework.odoo_patch.odoo.orm.models"
            ),
        ):
            self.env.ref("base.partner_admin").with_context(
                **{MODULE_UNINSTALL_FLAG: True}
            ).unlink()

    def test_02_invalid_view(self):
        """
        Test that we patch away fatal view errors and log the problem
        """
        base_view = self.env["ir.ui.view"].create(
            {
                "model": "res.partner",
                "arch": '<form><field name="nonexisting_field" /></form>',
            }
        )
        inherited_view1 = self.env["ir.ui.view"].create(
            {
                "model": "res.partner",
                "inherit_id": base_view.id,
                "arch": '<field name="nonexisting_field2" position="replace" />',
            }
        )
        inherited_view2 = inherited_view1.copy()
        with self.assertLogs(
            "odoo.addons.openupgrade_framework.odoo_patch.odoo.addons.base.models.ir_ui_view",
        ):
            (inherited_view1 + inherited_view2)._get_combined_archs()

    def _auto_install_vals(self, name, base):
        return {
            "name": name,
            "state": "uninstalled",
            "auto_install": "true",
            "dependencies_id": [
                fields.Command.create({"name": base.name}),
            ],
        }

    def _patched_update_list(self):
        model = self.env["ir.module.module"]
        func = getattr(type(model).update_list, "__func__", type(model).update_list)
        return func

    def test_03_update_list(self):
        """Only modules discovered by this update_list() call are auto-installed.

        A module that already has an ``ir.module.module`` row stays uninstalled.
        That is what keeps a deliberately removed auto_install module (``iap``
        from Odoo 18 on) from coming back. Localization modules are still ignored.
        """
        IrModuleModule = self.env["ir.module.module"]
        base = IrModuleModule.create(
            {
                "name": "openupgrade_framework_test_base",
                "state": "installed",
            }
        )
        preexisting = IrModuleModule.create(
            self._auto_install_vals("openupgrade_framework_test_auto_install", base)
        )
        preexisting_l10n = IrModuleModule.create(
            self._auto_install_vals("l10n_openupgrade_framework_localization", base)
        )

        def fake_original(module_model):
            IrModuleModule.create(
                self._auto_install_vals(
                    "openupgrade_framework_test_new_auto_install", base
                )
            )
            IrModuleModule.create(
                self._auto_install_vals("l10n_openupgrade_framework_test_new", base)
            )
            return [0, 2]

        func = self._patched_update_list()
        original = func._original_method
        func._original_method = fake_original
        self.addCleanup(setattr, func, "_original_method", original)
        module_model = IrModuleModule.with_context(
            openupgrade_auto_install_existing=False
        )
        os.environ.pop("OPENUPGRADE_AUTO_INSTALL_EXISTING", None)
        module_model.update_list()
        self.assertEqual(preexisting.state, "uninstalled")
        self.assertEqual(preexisting_l10n.state, "uninstalled")
        new = IrModuleModule.search(
            [("name", "=", "openupgrade_framework_test_new_auto_install")]
        )
        new_l10n = IrModuleModule.search(
            [("name", "=", "l10n_openupgrade_framework_test_new")]
        )
        self.assertEqual(new.state, "to install")
        self.assertEqual(new_l10n.state, "uninstalled")

    def test_04_update_list_install_existing(self):
        """``OPENUPGRADE_AUTO_INSTALL_EXISTING`` restores the previous behaviour."""
        IrModuleModule = self.env["ir.module.module"]
        base = IrModuleModule.create(
            {
                "name": "openupgrade_framework_test_base_legacy",
                "state": "installed",
            }
        )
        preexisting = IrModuleModule.create(
            self._auto_install_vals(
                "openupgrade_framework_test_auto_install_legacy", base
            )
        )
        os.environ["OPENUPGRADE_AUTO_INSTALL_EXISTING"] = "1"
        self.addCleanup(os.environ.pop, "OPENUPGRADE_AUTO_INSTALL_EXISTING", None)
        IrModuleModule.update_list()
        self.assertEqual(preexisting.state, "to install")
