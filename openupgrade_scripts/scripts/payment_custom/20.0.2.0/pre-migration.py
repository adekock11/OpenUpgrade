# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade


def _clear_deleted_redirect_form(env):
    """``payment_custom.redirect_form`` is removed in 20.0.

    ``payment.provider.redirect_form_view_id`` still points at that view, so
    deleting the view raises ``Could not delete obsolete record`` on the
    foreign key. No replacement redirect form is shipped for this provider
    (custom payments no longer post through that view), so the link is cleared.
    """
    cr = env.cr
    if not openupgrade.column_exists(cr, "payment_provider", "redirect_form_view_id"):
        return
    openupgrade.logged_query(
        cr,
        """
        UPDATE payment_provider
           SET redirect_form_view_id = NULL
         WHERE redirect_form_view_id IN (
                SELECT res_id
                  FROM ir_model_data
                 WHERE module = 'payment_custom'
                   AND name = 'redirect_form'
                   AND model = 'ir.ui.view'
               )
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _clear_deleted_redirect_form(env)
