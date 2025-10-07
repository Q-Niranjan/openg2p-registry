# Part of OpenG2P. See LICENSE file for full copyright and licensing details.

{
    "name": "G2P Registry Action",
    "category": "G2P",
    "summary": "Manage G2P Registry Model Actions ",
    "version": "17.0.0.0.0",
    "sequence": 3,
    "author": "OpenG2P",
    "website": "https://openg2p.org",
    "license": "LGPL-3",
    "depends": [
        "g2p_registry_model",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/registry_action_view.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}
