# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from openupgradelib import openupgrade

# The 20.0 manifest ships no data files. These records called
# crm.lead._form_view_auto_fill(), which was removed with the XML.
_DELETED_XMLIDS = [
    "crm_mail_plugin.crm_lead_action_form_edit",
    "crm_mail_plugin.lead_creation_prefilled_action",
]


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.delete_records_safely_by_xml_id(env, _DELETED_XMLIDS)
