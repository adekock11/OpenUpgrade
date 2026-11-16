# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

# Fields whose ir.model.fields xmlid moved from stock_account to account.
# upgrade_analysis: "module is now 'account' ('stock_account')".
_STOCK_ACCOUNT_FIELDS_MOVED_TO_ACCOUNT = (
    (
        "account.account",
        ["account_stock_expense_id", "account_stock_variation_id"],
    ),
    ("account.move.line", ["cogs_origin_id"]),
    (
        "product.category",
        [
            "account_stock_variation_id",
            "property_cost_method",
            "property_price_difference_account_id",
            "property_stock_journal",
            "property_stock_valuation_account_id",
            "property_valuation",
        ],
    ),
    ("product.product", ["cost_method", "valuation"]),
    ("product.template", ["cost_method", "valuation"]),
    (
        "res.company",
        [
            "account_stock_journal_id",
            "account_stock_valuation_id",
            "cost_method",
            "inventory_period",
            "inventory_valuation",
        ],
    ),
)

_STOCK_ACCOUNT_RENAMED_XMLIDS = [
    (
        "stock_account.action_report_stock_valuation",
        "account.action_report_stock_valuation",
    ),
    (
        "stock_account.ir_cron_post_stock_valuation",
        "account.ir_cron_post_stock_valuation",
    ),
]


def _move_stock_account_records(env):
    """Adopt stock_account records and fields that now belong to account.

    ``account.action_report_stock_valuation`` still uses the path
    ``stock-valuation-closing``. Account is loaded before stock_account, so
    the rename has to happen here: otherwise account's data file inserts a
    second client action and PostgreSQL raises ir_act_client_path_unique.
    """
    openupgrade.rename_xmlids(env.cr, _STOCK_ACCOUNT_RENAMED_XMLIDS)
    for model, field_names in _STOCK_ACCOUNT_FIELDS_MOVED_TO_ACCOUNT:
        openupgrade.update_module_moved_fields(
            env.cr, model, field_names, "stock_account", "account"
        )


@openupgrade.migrate()
def migrate(env, version):
    _move_stock_account_records(env)
