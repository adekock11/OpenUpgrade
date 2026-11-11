This module does not need to be installed on a database. It simply needs
to be available via your `addons-path`.

On Odoo 20 install openupgradelib from
`adekock11/openupgradelib` branch `cursor/fix-convert-xml-import-odoo20-3995`
(pull request 1). `load_data()` imports `convert_xml_import` from
`odoo.tools.convert` there. Pull request 2 is not part of that install:
Odoo 18.0, 19.0 and 20.0 share the same `exec_script` signature check, and
current openupgradelib already allow-lists `(env, version)`. See
`requirements.txt`.
