# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from openupgradelib import openupgrade

# crm_lead_views.xml left the manifest. The inherited views still point at
# lead fields this module no longer extends, so remove them before view
# validation. Module data loads the new industry tree/search views.
_DELETED_XMLIDS = [
    "crm_iap_mine.crm_case_kanban_view_leads",
    "crm_iap_mine.crm_lead_view_tree_lead",
    "crm_iap_mine.crm_lead_view_tree_opportunity",
    "crm_iap_mine.view_crm_lead_kanban",
]


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.delete_records_safely_by_xml_id(env, _DELETED_XMLIDS)
