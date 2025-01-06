import base64
import json
import logging
import mimetypes
from datetime import datetime

import jq
import requests
from dateutil import parser

from odoo import _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ODKClient:
    def __init__(
        self,
        env,
        _id,
        base_url,
        username,
        password,
        project_id,
        form_id,
        target_registry,
        json_formatter=".",
        backend_id=None,
    ):
        self.id = _id
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.project_id = project_id
        self.form_id = form_id
        self.session = None
        self.env = env
        self.json_formatter = json_formatter
        self.target_registry = target_registry
        self.backend_id = backend_id

    def login(self):
        login_url = f"{self.base_url}/v1/sessions"
        headers = {"Content-Type": "application/json"}
        data = json.dumps({"email": self.username, "password": self.password})
        try:
            response = requests.post(login_url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            if response.status_code == 200:
                self.session = response.json()["token"]
        except Exception as e:
            _logger.exception("Login failed: %s", e)
            raise ValidationError(f"Login failed: {e}") from e

    def test_connection(self):
        if not self.session:
            raise ValidationError(_("Session not created"))
        info_url = f"{self.base_url}/v1/users/current"
        headers = {"Authorization": f"Bearer {self.session}"}
        try:
            response = requests.get(info_url, headers=headers, timeout=10)
            response.raise_for_status()
            if response.status_code == 200:
                user = response.json()
                _logger.info(f'Connected to ODK Central as {user["displayName"]}')
                return True
        except Exception as e:
            _logger.exception("Connection test failed: %s", e)
            raise ValidationError(f"Connection test failed: {e}") from e

    # ruff: noqa: C901
    def import_delta_records(self, last_sync_timestamp=None, skip=0):
        url = f"{self.base_url}/v1/projects/{self.project_id}/forms/{self.form_id}.svc/Submissions"
        params = {
            "$skip": skip,
            "$count": "true",
            "$expand": "*",
        }
        if last_sync_timestamp:
            startdate = last_sync_timestamp.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            params["$filter"] = f"__system/submissionDate ge {startdate}"

        headers = {"Authorization": f"Bearer {self.session}"}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            _logger.exception("Failed to parse response: %s", e)
            raise ValidationError(f"Failed to parse response: {e}") from e

        # Sort the list of submissions based on the submission_time field if it exists
        data["value"] = sorted(
            data["value"],
            key=lambda x: (
                # True for invalid times, sorts to end
                x.get("submission_time") in (None, ""),
                parser.parse(x["submission_time"]) if x.get("submission_time") not in (None, "") else None,
            ),
        )
        partner_count = 0
        for member in data["value"]:
            _logger.debug("ODK RAW DATA:%s" % member)

            mapped_json = jq.first(self.json_formatter, member)
            if self.target_registry == "individual":
                mapped_json.update({"is_registrant": True, "is_group": False})
            elif self.target_registry == "group":
                mapped_json.update({"is_registrant": True, "is_group": True})

            self.handle_one2many_fields(mapped_json)
            self.handle_media_import(member, mapped_json)

            updated_mapped_json = self.get_addl_data(mapped_json)

            self.env["res.partner"].sudo().create(updated_mapped_json)
            partner_count += 1
            data.update({"form_updated": True})

        data.update({"partner_count": partner_count})

        return data

    def get_submissions(self, fields=None, last_sync_time=None):
        # Construct the API endpoint
        endpoint = f"{self.base_url}/v1/projects/{self.project_id}/forms/{self.form_id}.svc/Submissions"

        # Add query parameters to fetch only specific fields and filter by last sync time
        params = {}
        if fields:
            params["$select"] = fields
        if last_sync_time:
            startdate = last_sync_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            params["$filter"] = f"__system/submissionDate ge {startdate}"
        submissions = []
        headers = {"Authorization": f"Bearer {self.session}"}

        while endpoint:
            # Make the API request
            response = requests.get(endpoint, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            # Append the submissions
            data = response.json()
            if isinstance(data, dict):
                submissions.extend(data["value"])
            else:
                _logger.error("Unexpected response format: expected a dict of submissions")
                break

            # Handle pagination
            endpoint = None

        return submissions

    def handle_one2many_fields(self, mapped_json):
        if "phone_number_ids" in mapped_json:
            mapped_json["phone_number_ids"] = [
                (
                    0,
                    0,
                    {
                        "phone_no": phone.get("phone_no"),
                        "date_collected": phone.get("date_collected"),
                        "disabled": phone.get("disabled"),
                    },
                )
                for phone in mapped_json["phone_number_ids"]
            ]

        if "group_membership_ids" in mapped_json and self.target_registry == "group":
            individual_ids = []
            relationships_ids = []
            group_membership_data = (
                mapped_json.get("group_membership_ids")
                if mapped_json.get("group_membership_ids") is not None
                else []
            )

            for individual_mem in group_membership_data:
                individual_data = self.get_individual_data(individual_mem)
                individual = self.env["res.partner"].sudo().create(individual_data)
                if individual:
                    kind = self.get_member_kind(individual_mem)
                    individual_data = {"individual": individual.id}
                    if kind:
                        individual_data["kind"] = [(4, kind.id)]
                    relationship = self.get_member_relationship(individual.id, individual_mem)
                    if relationship:
                        relationships_ids.append((0, 0, relationship))
                    individual_ids.append((0, 0, individual_data))
            mapped_json["related_1_ids"] = relationships_ids
            mapped_json["group_membership_ids"] = individual_ids

        if "reg_ids" in mapped_json:
            mapped_json["reg_ids"] = [
                (
                    0,
                    0,
                    {
                        "id_type": self.env["g2p.id.type"]
                        .search([("name", "=", reg_id.get("id_type"))], limit=1)
                        .id,
                        "value": reg_id.get("value"),
                        "expiry_date": reg_id.get("expiry_date"),
                    },
                )
                for reg_id in mapped_json["reg_ids"]
            ]

    def handle_media_import(self, member, mapped_json):
        meta = member.get("meta")
        if not meta:
            return

        instance_id = meta.get("instanceID")
        if not instance_id:
            return

        all_attachments = self.list_expected_attachments(
            self.base_url, self.project_id, self.form_id, instance_id, self.session
        )
        if not all_attachments:
            return

        first_image_stored = False
        for attachment in all_attachments:
            filename = attachment["name"]
            get_attachment = self.download_attachment(
                self.base_url, self.project_id, self.form_id, instance_id, filename, self.session
            )
            attachment_base64 = base64.b64encode(get_attachment).decode("utf-8")
            image_verify = self.is_image(filename)

            if not first_image_stored and image_verify and "image_1920" in mapped_json:
                mapped_json["image_1920"] = attachment_base64
                first_image_stored = True
            else:
                if "supporting_documents_ids" not in mapped_json:
                    mapped_json["supporting_documents_ids"] = []

                mapped_json["supporting_documents_ids"].append(
                    (
                        0,
                        0,
                        {
                            "backend_id": self.backend_id,
                            "name": attachment["name"],
                            "data": attachment_base64,
                        },
                    )
                )

    def get_member_kind(self, record):
        kind_as_str = record.get("kind", None)
        kind = self.env["g2p.group.membership.kind"].search([("name", "=", kind_as_str)], limit=1)
        return kind

    def get_member_relationship(self, source_id, record):
        member_relation = record.get("relationship_with_head", None)
        relation = self.env["g2p.relationship"].search([("name", "=", member_relation)], limit=1)

        if relation:
            return {"source": source_id, "relation": relation.id, "start_date": datetime.now()}

        _logger.warning("No relation defined for member")

        return None

    def get_gender(self, gender_val):
        if gender_val:
            gender = self.env["gender.type"].sudo().search([("value", "=", gender_val)], limit=1)
            return gender.code if gender else None
        return None

    def get_dob(self, record):
        dob = record.get("birthdate")
        if dob:
            return dob

        age = record.get("age")
        if age:
            now = datetime.now()
            birth_year = now.year - age
            if birth_year < 0:
                _logger.warning("Future birthdate is not allowed.")
                return None
            return now.replace(year=birth_year).strftime("%Y-%m-%d")
        return None

    def get_individual_data(self, record):
        name = record.get("name", None)
        if name is not None:
            given_name = name.split(" ")[0]
            family_name = name.split(" ")[-1]
            addl_name = " ".join(name.split(" ")[1:-1])
        else:
            given_name = None
            family_name = None
            addl_name = None
        dob = self.get_dob(record)
        gender = self.get_gender(record.get("gender"))

        return {
            "name": name,
            "given_name": given_name,
            "family_name": family_name,
            "addl_name": addl_name,
            "is_registrant": True,
            "is_group": False,
            "birthdate": dob,
            "gender": gender,
        }

    def get_addl_data(self, mapped_json):
        # Override this method to add more data
        return mapped_json

    def is_image(self, filename):
        mimetype, _ = mimetypes.guess_type(filename)
        return mimetype and mimetype.startswith("image")

    def list_expected_attachments(self, base_url, project_id, form_id, instance_id, session_token):
        url = f"{base_url}/v1/projects/{project_id}/forms/{form_id}/submissions/{instance_id}/attachments"
        headers = {"Authorization": f"Bearer {session_token}"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def download_attachment(self, base_url, project_id, form_id, instance_id, filename, session_token):
        url = (
            f"{base_url}/v1/projects/{project_id}/forms/{form_id}/"
            f"submissions/{instance_id}/attachments/{filename}"
        )
        headers = {"Authorization": f"Bearer {session_token}"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.content

    #  Fetch Record using Instance ID
    def import_record_by_instance_id(self, instance_id, last_sync_timestamp=None):
        url = (
            f"{self.base_url}/v1/projects/{self.project_id}/forms/{self.form_id}.svc/"
            f"Submissions('{instance_id}')"
        )
        headers = {"Authorization": f"Bearer {self.session}"}
        params = {
            "$skip": 0,
            "$count": "true",
            "$expand": "*",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            _logger.exception("Failed to parse response by using instance ID: %s", e)
            raise ValidationError(f"Failed to parse response by using instance ID: {e}") from e

        _logger.debug(f"ODK RAW DATA by instance ID %s {instance_id} {data}")

        for member in data["value"]:
            mapped_json = jq.first(self.json_formatter, member)

            if self.target_registry == "individual":
                mapped_json.update({"is_registrant": True, "is_group": False})
            elif self.target_registry == "group":
                mapped_json.update({"is_registrant": True, "is_group": True})

            self.handle_one2many_fields(mapped_json)
            self.handle_media_import(member, mapped_json)

            updated_mapped_json = self.get_addl_data(mapped_json)

            self.env["res.partner"].sudo().create(updated_mapped_json)

        data.update({"form_updated": True})

        return data
