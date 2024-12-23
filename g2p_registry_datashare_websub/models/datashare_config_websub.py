import logging
import os
from datetime import datetime, timedelta
from urllib.parse import parse_qs

import jq
import requests

from odoo import api, fields, models, tools

from ..json_encoder import WebSubJSONEncoder

_logger = logging.getLogger(__name__)

WEBSUB_BASE_URL = os.getenv("WEBSUB_BASE_URL", "http://websub/hub")
WEBSUB_AUTH_URL = os.getenv(
    "WEBSUB_AUTH_URL",
    "http://keycloak.keycloak/realms/master/protocol/openid-connect/token",
)
WEBSUB_AUTH_CLIENT_ID = os.getenv("WEBSUB_AUTH_CLIENT_ID", "openg2p-admin-client")
WEBSUB_AUTH_CLIENT_SECRET = os.getenv("WEBSUB_AUTH_CLIENT_SECRET", "")
WEBSUB_AUTH_GRANT_TYPE = os.getenv("WEBSUB_AUTH_GRANT_TYPE", "client_credentials")


class G2PDatashareConfigWebsub(models.Model):
    _name = "g2p.datashare.config.websub"
    _description = "G2P Datashare Config WebSub"

    name = fields.Char(required=True)

    partner_id = fields.Char(string="Partner ID")

    event_type = fields.Selection(
        [
            ("GROUP_CREATED", "GROUP_CREATED"),
            ("GROUP_UPDATED", "GROUP_UPDATED"),
            ("GROUP_DELETED", "GROUP_DELETED"),
            ("INDIVIDUAL_CREATED", "INDIVIDUAL_CREATED"),
            ("INDIVIDUAL_UPDATED", "INDIVIDUAL_UPDATED"),
            ("INDIVIDUAL_DELETED", "INDIVIDUAL_DELETED"),
        ],
        required=True,
    )
    topic_joiner = fields.Char(default="/")

    transform_data_jq = fields.Text(
        string="Data Transform JQ Expression",
        default="""{
    ts_ms: .curr_datetime,
    event: .publisher.event_type,
    groupData: .record_data
}""",
    )
    condition_jq = fields.Text(string="Condition JQ Expression", default="true")

    websub_base_url = fields.Char("WebSub Base URL", default=WEBSUB_BASE_URL)
    websub_auth_url = fields.Char("WebSub Auth URL (Token Endpoint)", default=WEBSUB_AUTH_URL)
    websub_auth_client_id = fields.Char("WebSub Auth Client ID", default=WEBSUB_AUTH_CLIENT_ID)
    websub_auth_client_secret = fields.Char(default=WEBSUB_AUTH_CLIENT_SECRET)
    websub_auth_grant_type = fields.Char(default=WEBSUB_AUTH_GRANT_TYPE)
    websub_api_timeout = fields.Integer("WebSub API Timeout", default=10)

    websub_access_token = fields.Char()
    websub_access_token_expiry = fields.Datetime()

    active = fields.Boolean(required=True, default=True)

    @api.model_create_multi
    def create(self, vals):
        res = super().create(vals)
        for rec in res:
            rec.register_websub_event()
        return res

    def write(self, vals):
        try:
            if isinstance(vals, dict) and ("event_type" in vals or "partner_id" in vals):
                for rec in self:
                    rec.deregister_websub_event()
        except Exception:
            _logger.exception("WebSub - Changed event: couldnt deregister")
        res = super().write(vals)
        if isinstance(vals, dict) and ("event_type" in vals or "partner_id" in vals):
            for rec in self:
                rec.register_websub_event()
        return res

    def unlink(self):
        for rec in self:
            rec.deregister_websub_event()
        return super().unlink()

    @api.model
    def publish_event(self, event_type, data: dict):
        publishers = self.get_publishers(event_type)
        if not publishers:
            return
        for publisher in publishers:
            publisher.publish_by_publisher(data)

    def publish_by_publisher(self, data: dict):
        self.ensure_one()
        web_base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url").rstrip("/")
        curr_datetime = f'{datetime.now().isoformat(timespec = "milliseconds")}Z'

        record_id = data["id"]
        record = self.env["res.partner"].browse(record_id)
        record_data = self.get_full_record_data(record)
        record_data = WebSubJSONEncoder.python_dict_to_json_dict(
            {
                "web_base_url": web_base_url,
                "publisher": self.read()[0],
                "curr_datetime": curr_datetime,
                "data": data,
                "record_data": record_data,
            },
        )

        if not jq.first(self.condition_jq, record_data):
            return

        data_transformed = jq.first(
            self.transform_data_jq,
            record_data,
        )
        self.publish_event_websub(data_transformed)

    def publish_event_websub(self, data):
        self.ensure_one()
        token = self.get_access_token()
        res = requests.post(
            self.websub_base_url,
            params={
                "hub.mode": "publish",
                "hub.topic": (
                    f"{self.partner_id}"
                    f"{self.topic_joiner if self.partner_id else ''}"
                    f"{self.event_type}"
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
            json=data,
            timeout=self.websub_api_timeout,
        )
        res.raise_for_status()
        _logger.info("WebSub Publish Success. Response: %s. Headers: %s", res.text, res.headers)
        res = parse_qs(res.text)
        if not len(res.get("hub.mode", [])) or res["hub.mode"][0].lower() != "accepted":
            raise ValueError("WebSub Publish: Invalid hub response")

    def register_websub_event(self, mode="register"):
        self.ensure_one()
        token = self.get_access_token()
        res = requests.post(
            self.websub_base_url,
            headers={"Authorization": f"Bearer {token}"},
            data={
                "hub.mode": mode,
                "hub.topic": (
                    f"{self.partner_id}"
                    f"{self.topic_joiner if self.partner_id else ''}"
                    f"{self.event_type}"
                ),
            },
            timeout=self.websub_api_timeout,
        )
        res.raise_for_status()
        _logger.info(
            "WebSub Topic Registration/Deregistration Successful. Response: %s. Headers: %s",
            res.text,
            res.headers,
        )
        res = parse_qs(res.text)
        if not len(res.get("hub.mode", [])) or res["hub.mode"][0].lower() != "accepted":
            raise ValueError("WebSub Topic Register: Invalid hub response")

    def deregister_websub_event(self):
        return self.register_websub_event(mode="deregister")

    def get_access_token(self):
        self.ensure_one()
        if (
            self.websub_access_token
            and self.websub_access_token_expiry
            and self.websub_access_token_expiry > datetime.now()
        ):
            return self.websub_access_token
        data = {
            "client_id": self.websub_auth_client_id,
            "client_secret": self.websub_auth_client_secret,
            "grant_type": self.websub_auth_grant_type,
        }
        response = requests.post(self.websub_auth_url, data=data, timeout=self.websub_api_timeout)
        _logger.debug("WebSub Token response: %s", response.text)
        response.raise_for_status()
        response = response.json()
        access_token = response.get("access_token", None)
        token_exp = response.get("expires_in", None)
        self.sudo().write(
            {
                "websub_access_token": access_token,
                "websub_access_token_expiry": (
                    (datetime.now() + timedelta(seconds=token_exp))
                    if isinstance(token_exp, int)
                    else (datetime.fromisoformat(token_exp) if isinstance(token_exp, str) else token_exp)
                ),
            }
        )
        return access_token

    @tools.ormcache("event_type")
    def get_publishers(self, event_type):
        return self.search([("event_type", "=", event_type), ("active", "=", True)])

    def get_full_record_data(self, records):
        response = []
        record_data = records.read()
        for i, rec in enumerate(records):
            record_data[i]["image"] = self.get_image_base64_data_in_url((rec.image_1920 or b"").decode())
            record_data[i]["reg_ids"] = {reg_id.id_type.name: reg_id.value for reg_id in rec.reg_ids}
            if rec.is_group:
                members = rec.group_membership_ids
                members_data = members.read()
                for i, member in enumerate(members):
                    members_data[i]["individual"] = self.get_full_record_data(member.individual)
                record_data[i]["group_membership_ids"] = members_data
            response.append(record_data)
        return response

    @api.model
    def get_image_base64_data_in_url(self, image_base64: str) -> str:
        if not image_base64:
            return None
        image = tools.base64_to_image(image_base64)
        return f"data:image/{image.format.lower()};base64,{image_base64}"
