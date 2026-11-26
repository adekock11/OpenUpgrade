env = locals().get("env")
# An "on creation" rule with a domain: in 17.0 its trigger fields get filled
# during the migration, which must not wipe the domain.
env["base.automation"].create(
    {
        "name": "Openupgrade test rule with domain",
        "model_id": env.ref("base.model_res_partner").id,
        "trigger": "on_create",
        "state": "code",
        "code": "# nothing to do",
        "filter_domain": '[("name", "ilike", "openupgrade")]',
    }
)
# Same rule without a domain, which has to stay without one.
env["base.automation"].create(
    {
        "name": "Openupgrade test rule without domain",
        "model_id": env.ref("base.model_res_partner").id,
        "trigger": "on_create",
        "state": "code",
        "code": "# nothing to do",
    }
)
env.cr.commit()
