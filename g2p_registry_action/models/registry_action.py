from odoo import fields, models


class G2PRegistryAction(models.Model):
    _name = "g2p.registry.action"
    _description = "G2P Registry Action"

    registry_model_id = fields.Many2one(
        "g2p.registry.model",
        string="Registry Model",
        help="The specific registry model linked to this action.",
    )

    action_name = fields.Char(required=True)
    form_builder_id = fields.Many2one(
        "formio.builder",
        string="FormIO",
    )
    action_submission_url = fields.Char(help="API endpoint for submitting data")
