# Part of OpenG2P Registry. See LICENSE file for full copyright and licensing details.
{
    "name": "G2P Registry: Rest API",
    "category": "G2P",
    "version": "15.0.1.0.6",
    "sequence": 1,
    "author": "OpenG2P",
    "website": "https://github.com/openg2p/openg2p-registry",
    "license": "Other OSI approved licence",
    "development_status": "Alpha",
    "maintainers": ["jeremi", "gonzalesedwin1123", "emjay0921"],
    "depends": [
        "base",
        "mail",
        "contacts",
        "component",
        "base_rest",
        "pydantic",
        "base_rest_pydantic",
        "extendable",
        "g2p_registry_group",
        "g2p_registry_individual",
        "base_rest_auth_user_service",
    ],
    "external_dependencies": {"python": ["extendable-pydantic", "pydantic"]},
    "data": [
        "security/g2p_security.xml",
        "security/ir.model.access.csv",
    ],
    "assets": {},
    "demo": [],
    "images": [],
    "application": True,
    "installable": True,
    "auto_install": False,
}
