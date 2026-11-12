"""Encode any known changes to the database here
to help the matching process
"""

# Renamed modules is a mapping from old module name to new module name
renamed_modules = {
    # odoo
    # odoo/enterprise
    # OCA/...
}

# Merged modules contain a mapping from old module names to other,
# preexisting module names
merged_modules = {
    # odoo
    # odoo/enterprise
    # OCA/...
}

# only used here for upgrade_analysis
renamed_models = {
    # odoo
    # OCA/...
}

# only used here for upgrade_analysis
merged_models = {
    # odoo
    # OCA/...
}

# Modules dropped from the distribution. base pre-migration marks them
# ``to remove`` so Odoo uninstalls their views and assets.
removed_modules = [
    # odoo/design-themes: snippets library removed in 20.0, not folded into website
    "theme_common",
]
