"""
Test suite for Gupshup WhatsApp Integration
- Webhook setup via Partner Subscription API
- Send WhatsApp messages
- Chat history
- WhatsApp templates
- Webhook handler for inbound messages (V2 & V3 formats)
"""
import pytest
import requests
import os
import json
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "roshini@arihant.com"
TEST_PASSWORD = "arihant123"
TEST_PHONE = "918696979791"


class TestAuth:
    """Authentication tests for getting Bearer token"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token via OAuth2 password flow"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access token in response"
        return data["access_token"]
    
    def test_login_success(self, auth_token):
        """Test successful login"""
        assert auth_token is not None
        print(f"✓ Login successful, got token: {auth_token[:20]}...")


@pytest.fixture(scope="module")
def auth_headers():
    """Get auth headers for authenticated requests"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if response.status_code != 200:
        pytest.skip(f"Login failed: {response.text}")
    token = response.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


class TestGupshupWebhookSetup:
    """Tests for Gupshup webhook setup via Partner Subscription API"""
    
    def test_setup_webhook(self, auth_headers):
        """POST /api/integrations/gupshup/setup-webhook - setup webhook subscription"""
        response = requests.post(
            f"{BASE_URL}/api/integrations/gupshup/setup-webhook",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Setup webhook failed: {response.text}"
        data = response.json()
        print(f"✓ Webhook setup response: {json.dumps(data, indent=2)[:500]}")
        # Verify response structure
        assert "webhook_url" in data, "Missing webhook_url in response"
        # The setup may or may not succeed depending on Gupshup credentials, but API should return properly
    
    def test_get_subscriptions(self, auth_headers):
        """GET /api/integrations/gupshup/subscriptions - get active subscriptions"""
        response = requests.get(
            f"{BASE_URL}/api/integrations/gupshup/subscriptions",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get subscriptions failed: {response.text}"
        data = response.json()
        print(f"✓ Subscriptions response: {json.dumps(data, indent=2)[:500]}")
        # Should have subscriptions key
        assert "subscriptions" in data or "success" in data, "Invalid response structure"
    
    def test_get_webhook_status(self, auth_headers):
        """GET /api/integrations/gupshup/webhook-status - get webhook configuration status"""
        response = requests.get(
            f"{BASE_URL}/api/integrations/gupshup/webhook-status",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get webhook status failed: {response.text}"
        data = response.json()
        print(f"✓ Webhook status response: {json.dumps(data, indent=2)[:500]}")
        # Should have webhook_endpoint
        assert "webhook_endpoint" in data, "Missing webhook_endpoint in response"
        assert data["webhook_endpoint"] == "/api/whatsapp/webhook"


class TestWhatsAppTemplates:
    """Tests for WhatsApp templates from Gupshup"""
    
    def test_get_templates(self, auth_headers):
        """GET /api/whatsapp/templates - get list of WhatsApp templates"""
        response = requests.get(
            f"{BASE_URL}/api/whatsapp/templates",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get templates failed: {response.text}"
        data = response.json()
        print(f"✓ Templates response: {json.dumps(data, indent=2)[:500]}")
        # Should have success key
        assert "success" in data or "templates" in data, "Invalid response structure"


class TestWhatsAppWebhook:
    """Tests for WhatsApp webhook handler (NO AUTH required - called by Gupshup)"""
    
    def test_v3_webhook_format(self):
        """POST /api/whatsapp/webhook - V3 format incoming message"""
        # V3 format payload (new subscription API format)
        v3_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{
                            "wa_id": TEST_PHONE,
                            "profile": {"name": "Test Customer V3"}
                        }],
                        "messages": [{
                            "from": TEST_PHONE,
                            "id": f"v3_test_msg_{int(time.time())}",
                            "type": "text",
                            "text": {"body": "Hello from V3 webhook test!"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/whatsapp/webhook",
            json=v3_payload,
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200, f"V3 webhook failed: {response.text}"
        data = response.json()
        print(f"✓ V3 webhook response: {data}")
        assert data.get("status") == "ok", "V3 webhook didn't return ok status"
    
    def test_v2_webhook_format(self):
        """POST /api/whatsapp/webhook - V2 format incoming message"""
        # V2 format payload (legacy format)
        v2_payload = {
            "type": "message",
            "messageId": f"v2_test_msg_{int(time.time())}",
            "payload": {
                "sender": {
                    "phone": TEST_PHONE,
                    "name": "Test Customer V2"
                },
                "type": "text",
                "payload": {
                    "text": "Hello from V2 webhook test!"
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/whatsapp/webhook",
            json=v2_payload,
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200, f"V2 webhook failed: {response.text}"
        data = response.json()
        print(f"✓ V2 webhook response: {data}")
        assert data.get("status") == "ok", "V2 webhook didn't return ok status"
    
    def test_webhook_handles_empty_body(self):
        """POST /api/whatsapp/webhook - handles empty or invalid body gracefully"""
        response = requests.post(
            f"{BASE_URL}/api/whatsapp/webhook",
            data="",  # Empty body
            headers={"Content-Type": "application/json"}
        )
        # Should return 200 to prevent Gupshup retries
        assert response.status_code == 200, f"Empty webhook failed: {response.text}"


class TestChatHistory:
    """Tests for WhatsApp chat history endpoints"""
    
    def test_get_chat_history_by_phone(self, auth_headers):
        """GET /api/whatsapp/chat-history/{phone} - get chat history for phone"""
        response = requests.get(
            f"{BASE_URL}/api/whatsapp/chat-history/{TEST_PHONE}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get chat history failed: {response.text}"
        data = response.json()
        print(f"✓ Chat history response: phone={data.get('phone')}, count={data.get('count')}")
        # Verify response structure
        assert "phone" in data, "Missing phone in response"
        assert "messages" in data, "Missing messages in response"
        assert "count" in data, "Missing count in response"
        # Should have messages from webhook tests
        print(f"  Messages found: {data.get('count')}")
        if data.get("messages"):
            for msg in data["messages"][:3]:
                print(f"    - {msg.get('direction')}: {msg.get('content', '')[:50]}")


class TestLeadChat:
    """Tests for lead-specific WhatsApp endpoints"""
    
    @pytest.fixture(scope="class")
    def test_lead_id(self, auth_headers):
        """Get a test lead ID from the leads API"""
        response = requests.get(
            f"{BASE_URL}/api/leads?search=Test",
            headers=auth_headers
        )
        if response.status_code != 200:
            # Try getting any lead
            response = requests.get(
                f"{BASE_URL}/api/leads?limit=5",
                headers=auth_headers
            )
        if response.status_code == 200:
            leads = response.json()
            if leads:
                return leads[0].get("id")
        pytest.skip("No leads found for testing")
    
    def test_get_lead_chat_history(self, auth_headers, test_lead_id):
        """GET /api/whatsapp/lead-chat/{lead_id} - get chat history for lead"""
        response = requests.get(
            f"{BASE_URL}/api/whatsapp/lead-chat/{test_lead_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get lead chat failed: {response.text}"
        data = response.json()
        print(f"✓ Lead chat history response: {json.dumps(data, indent=2)[:300]}")
        # Should have messages array even if empty
        assert "messages" in data or "error" in data


class TestSendWhatsApp:
    """Tests for sending WhatsApp messages"""
    
    def test_send_message_to_phone(self, auth_headers):
        """POST /api/whatsapp/send - send a WhatsApp text message"""
        payload = {
            "destination": TEST_PHONE,
            "message_type": "text",
            "text": f"Test message from pytest at {datetime.now().isoformat()}"
        }
        response = requests.post(
            f"{BASE_URL}/api/whatsapp/send",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200, f"Send message failed: {response.text}"
        data = response.json()
        print(f"✓ Send message response: {json.dumps(data, indent=2)[:300]}")
        # Response should indicate success or failure (Gupshup might reject)
        assert "success" in data or "error" in data or "status" in data
    
    def test_send_message_to_lead(self, auth_headers):
        """POST /api/whatsapp/send-to-lead/{lead_id} - send message to lead"""
        # First get a lead
        leads_response = requests.get(
            f"{BASE_URL}/api/leads?limit=1",
            headers=auth_headers
        )
        if leads_response.status_code != 200 or not leads_response.json():
            pytest.skip("No leads available for testing")
        
        lead = leads_response.json()[0]
        lead_id = lead.get("id")
        
        payload = {
            "destination": lead.get("phone", TEST_PHONE),
            "message_type": "text",
            "text": f"Test message to lead from pytest at {datetime.now().isoformat()}"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/whatsapp/send-to-lead/{lead_id}",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200, f"Send to lead failed: {response.text}"
        data = response.json()
        print(f"✓ Send to lead response: {json.dumps(data, indent=2)[:300]}")


class TestEdgeCases:
    """Edge case tests"""
    
    def test_chat_history_invalid_phone(self, auth_headers):
        """GET /api/whatsapp/chat-history/{phone} - with invalid phone returns empty"""
        response = requests.get(
            f"{BASE_URL}/api/whatsapp/chat-history/0000000000",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Invalid phone should still return 200"
        data = response.json()
        assert data.get("count", 0) == 0, "Invalid phone should have 0 messages"
    
    def test_lead_chat_invalid_lead(self, auth_headers):
        """GET /api/whatsapp/lead-chat/{lead_id} - with invalid lead returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/whatsapp/lead-chat/invalid-lead-id",
            headers=auth_headers
        )
        assert response.status_code == 404, "Invalid lead should return 404"
    
    def test_send_message_missing_destination(self, auth_headers):
        """POST /api/whatsapp/send - missing destination should fail"""
        payload = {
            "message_type": "text",
            "text": "Test message"
        }
        response = requests.post(
            f"{BASE_URL}/api/whatsapp/send",
            json=payload,
            headers=auth_headers
        )
        # Should return 400 or 422 for missing destination
        assert response.status_code in [400, 422], f"Missing destination should fail validation"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
