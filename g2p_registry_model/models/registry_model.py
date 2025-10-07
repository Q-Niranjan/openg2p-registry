import uuid

from odoo import api, fields, models


class G2PRegistryModel(models.Model):
    _name = "g2p.registry.model"
    _description = "G2P Registry Model"
    _rec_name = "registry_name"

    registry_name = fields.Char(required=True, help="Name of the registry")

    registry_unique_id = fields.Char(
        required=True,
        index=True,
        copy=False,
        readonly=True,
        default=lambda self: str(uuid.uuid4()),
        help="Unique identifier for the registry",
    )

    registry_creation_date = fields.Datetime(
        default=fields.Datetime.now, readonly=True, help="Date when the registry was created"
    )

    registry_last_updation_date = fields.Datetime(help="Last updated timestamp for the registry record")

    registry_details = fields.Text(help="Additional details about the registry")

    registry_model = fields.Many2one("ir.model", help="Associated model name related to this registry")

    _sql_constraints = [
        ("registry_unique_id_uniq", "UNIQUE(registry_unique_id)", "The registry unique ID must be unique!")
    ]

    @api.model
    def create(self, vals):
        vals["registry_creation_date"] = fields.Datetime.now()
        return super().create(vals)

    def write(self, vals):
        vals["registry_last_updation_date"] = fields.Datetime.now()
        return super().write(vals)
