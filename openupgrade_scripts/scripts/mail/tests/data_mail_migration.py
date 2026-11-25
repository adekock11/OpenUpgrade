env = locals().get("env")
test_user = env["res.users"].search([("login", "=", "test_user_v19")])
env["discuss.channel"].with_user(test_user).create(
    {
        "name": "OpenUpgrade v20 test channel",
    }
)
partner = (
    env["res.partner"]
    .with_context(mail_create_nolog=True, tracking_disable=True)
    .create({"name": "OpenUpgrade tracking body partner"})
)
tracking_field = env["ir.model.fields"]._get("res.partner", "ref")
message = env["mail.message"].create(
    {
        "model": "res.partner",
        "res_id": partner.id,
        "body": False,
        "message_type": "notification",
        "subtype_id": env.ref("mail.mt_note").id,
        "author_id": test_user.partner_id.id,
        "subject": "OpenUpgrade tracking body",
    }
)
env["mail.tracking.value"].create(
    {
        "mail_message_id": message.id,
        "field_id": tracking_field.id,
        "old_value_char": "OU-OLD-REF",
        "new_value_char": "OU-NEW-REF",
    }
)
env.cr.commit()
