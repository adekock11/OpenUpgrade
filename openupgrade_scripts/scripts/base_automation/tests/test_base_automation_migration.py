from odoo.tests import TransactionCase

from odoo.addons.openupgrade_framework import openupgrade_test


@openupgrade_test
class TestBaseAutomationMigration(TransactionCase):
    def test_on_create_filter_domain_kept(self):
        """
        An on_create rule gets create_date as trigger field during the
        migration. The filter domain of the rule must survive that.
        """
        rule = self.env["base.automation"].search(
            [("name", "=", "Openupgrade test rule with domain")]
        )
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule.trigger, "on_create")
        self.assertEqual(rule.trigger_field_ids.mapped("name"), ["create_date"])
        self.assertEqual(rule.filter_domain, '[("name", "ilike", "openupgrade")]')

    def test_on_create_without_filter_domain(self):
        rule = self.env["base.automation"].search(
            [("name", "=", "Openupgrade test rule without domain")]
        )
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule.trigger_field_ids.mapped("name"), ["create_date"])
        self.assertFalse(rule.filter_domain)
