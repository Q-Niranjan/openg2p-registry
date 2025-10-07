# Part of OpenG2P. See LICENSE file for full copyright and licensing details.
{
    "name": "G2P Registry Model",
    "category": "G2P",
    "summary": "Manage Different Types of G2P Registry Model  ",
    "version": "17.0.0.0.0",
    "sequence": 3,
    "author": "OpenG2P",
    "website": "https://openg2p.org",
    "license": "LGPL-3",
    "depends": [
        "base",
        "g2p_registry_base",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/menu.xml",
        "views/registry_model_view.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}
