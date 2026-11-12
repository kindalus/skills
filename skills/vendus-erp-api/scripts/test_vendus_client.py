"""Offline checks: python3 -m unittest discover -s skills/vendus-erp-api/scripts."""
import copy
import unittest
from unittest.mock import Mock

import requests

from vendus_client import BASE_URL, VendusClient, VendusError


class DocumentCreationTests(unittest.TestCase):
    def setUp(self):
        self.client = VendusClient(api_key="test-only-not-a-real-key")
        self.client._session = Mock()
        self.client._session.post.return_value.status_code = 201
        self.client._session.post.return_value.json.return_value = {
            "id": 42, "number": "FT TEST/42",
        }
        self.payload = {
            "type": "FT", "register_id": 1, "mode": "tests",
            "external_reference": "test-order-42",
            "client": {"id": 2},
            "items": [{"id": 3, "qty": "1.5", "gross_price": "100.00"}],
        }

    def test_confirmation_is_required(self):
        for confirmation in (False, None, "yes", 1):
            with self.subTest(confirmation=confirmation), self.assertRaises(VendusError):
                self.client.create_document(self.payload, confirmed=confirmation)
        self.client._session.post.assert_not_called()

    def test_posts_exact_payload_once_without_redirects(self):
        before = copy.deepcopy(self.payload)
        result = self.client.create_document(self.payload, confirmed=True)
        self.assertEqual(result["id"], 42)
        self.assertEqual(self.payload, before)
        self.client._session.post.assert_called_once_with(
            f"{BASE_URL}/documents/", json=self.payload,
            timeout=30, allow_redirects=False,
        )

    def test_invalid_payloads_never_reach_network(self):
        changes = [
            {"type": ""}, {"register_id": None}, {"mode": "preview"},
            {"external_reference": " "}, {"output": "pdf"},
            {"supplier": {"name": "New supplier"}},
            {"client": {"name": "New client"}},
            {"client": {"id": 2, "send_email": "yes"}},
            {"items": []}, {"items": [{"reference": "NEW", "qty": 1}]},
            {"items": [{"id": 3, "title": "Changed title", "qty": 1}]},
            *({"items": [{"id": 3, "qty": qty}]} for qty in (0, -1, "NaN", "inf", "bad", None)),
            {"type": "NC"}, {"type": "RG"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(VendusError):
                self.client.create_document(self.payload | change, confirmed=True)
        self.client._session.post.assert_not_called()

    def test_other_hosts_are_blocked(self):
        self.client.base_url = "https://example.org"
        with self.assertRaises(VendusError):
            self.client.create_document(self.payload, confirmed=True)
        self.client._session.post.assert_not_called()

    def test_receipt_has_invoices_and_payments_but_no_items(self):
        payload = self.payload | {
            "type": "RG", "invoices": [{"document_number": "FT TEST/1"}],
            "payments": [{"id": "4", "amount": "150.00"}],
        }
        del payload["items"]
        self.client.create_document(payload, confirmed=True)
        self.client._session.post.assert_called_once()

    def test_credit_note_requires_reason_and_original_row(self):
        payload = self.payload | {"type": "NC", "notes": "Returned product"}
        payload["items"] = [{"id": 3, "qty": 1, "reference_document": {
            "document_number": "FT TEST/1", "document_row": 1,
        }}]
        self.client.create_document(payload, confirmed=True)
        self.client._session.post.assert_called_once()
        for change in ({"notes": ""}, {"items": [{"id": 3, "qty": 1}]}):
            with self.assertRaises(VendusError):
                self.client.create_document(payload | change, confirmed=True)
        self.assertEqual(self.client._session.post.call_count, 1)

    def test_uncertain_outcomes_never_retry(self):
        for status in (301, 403, 500):
            self.client._session.post.reset_mock()
            self.client._session.post.return_value.status_code = status
            with self.assertRaisesRegex(VendusError, "reconcile"):
                self.client.create_document(self.payload, confirmed=True)
            self.client._session.post.assert_called_once()
        self.client._session.post.return_value.status_code = 201
        for outcome in (ValueError("bad JSON"), {}, {"number": "FT TEST/42"}):
            self.client._session.post.reset_mock()
            response = self.client._session.post.return_value
            response.json.side_effect = outcome if isinstance(outcome, Exception) else None
            response.json.return_value = outcome
            with self.assertRaisesRegex(VendusError, "reconcile"):
                self.client.create_document(self.payload, confirmed=True)
            self.client._session.post.assert_called_once()
        for error in (requests.Timeout(), requests.ConnectionError()):
            self.client._session.post.reset_mock()
            self.client._session.post.side_effect = error
            with self.assertRaisesRegex(VendusError, "outcome is unknown"):
                self.client.create_document(self.payload, confirmed=True)
            self.client._session.post.assert_called_once()

    def test_queries_still_work(self):
        response = self.client._session.get.return_value
        response.ok = True
        response.json.return_value = [{"id": 42}]
        response.headers = {}
        self.assertEqual(self.client.list_documents(type="FT"), [{"id": 42}])
        self.client._session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
