# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def _compute_activity_phone(env):
    """Fill mail.activity.phone, which is created in the pre-migration.

    Only phone call activities have a phone number. It is computed here, and
    not in the post-migration of mail, because the record of an activity can
    belong to a model of a module that loads after mail (crm.lead, ...).
    Activities of a model that is not in the registry (module not installed
    any more) keep an empty phone.
    """
    activities = env["mail.activity"].search(
        [
            ("activity_type_id.category", "=", "phonecall"),
            ("res_model", "in", list(env.registry.models)),
            ("res_id", "!=", 0),
        ]
    )
    activities._compute_phone()
    _logger.info("Computed the phone of %s phone call activities", len(activities))


@openupgrade.migrate()
def migrate(env, version):
    _compute_activity_phone(env)
