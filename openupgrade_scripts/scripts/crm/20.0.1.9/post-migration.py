# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from openupgradelib import openupgrade

# Data files that defined these records were removed from the manifest, so
# module loading does not delete them until the very end of the upgrade.
# Drop them before view validation: the wizard view targets a transient
# model that no longer exists, and the server actions call removed methods.
_DELETED_XMLIDS = [
    "crm.action_crm_lead2opportunity_partner",
    "crm.action_opportunity_forecast",
    "crm.action_your_pipeline",
    "crm.view_crm_lead2opportunity_partner",
    "crm.crm_lead_all_leads_view_calendar",
]


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.delete_records_safely_by_xml_id(env, _DELETED_XMLIDS)
