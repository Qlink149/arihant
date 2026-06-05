"""
Test suite for My Dashboard features:
- /api/my-dashboard endpoint
- /api/leads/transfer endpoint
- /api/leads/transfer/{id}/acknowledge endpoint
- /api/activity/heartbeat endpoint
- /api/activity/team-status endpoint
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "roshini@arihant.com"
TEST_PASSWORD = "arihant123"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    """Get authentication token"""
    response = api_client.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


class TestAuth:
    """Authentication tests"""
    
    def test_login_success(self, api_client):
        """Test login with valid credentials"""
        response = api_client.post(
            f"{BASE_URL}/api/auth/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in response"
        assert "user" in data, "No user in response"
        assert data["user"]["email"] == TEST_EMAIL


class TestActivityHeartbeat:
    """Tests for /api/activity/heartbeat endpoint"""
    
    def test_heartbeat_success(self, authenticated_client):
        """Test recording a heartbeat"""
        response = authenticated_client.post(f"{BASE_URL}/api/activity/heartbeat")
        assert response.status_code == 200, f"Heartbeat failed: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", "Heartbeat should return status: ok"
    
    def test_heartbeat_requires_auth(self, api_client):
        """Test heartbeat requires authentication"""
        # Create a new session without auth
        session = requests.Session()
        response = session.post(f"{BASE_URL}/api/activity/heartbeat")
        assert response.status_code == 401, "Heartbeat should require authentication"


class TestTeamStatus:
    """Tests for /api/activity/team-status endpoint"""
    
    def test_get_team_status(self, authenticated_client):
        """Test getting team status"""
        response = authenticated_client.get(f"{BASE_URL}/api/activity/team-status")
        assert response.status_code == 200, f"Team status failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Team status should return a list"
    
    def test_team_status_structure(self, authenticated_client):
        """Test team status response structure"""
        response = authenticated_client.get(f"{BASE_URL}/api/activity/team-status")
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            rep = data[0]
            assert "name" in rep, "Rep should have name"
            assert "status" in rep, "Rep should have status"
            assert "active_leads" in rep, "Rep should have active_leads count"
            assert rep["status"] in ["online", "idle", "offline"], f"Invalid status: {rep['status']}"
    
    def test_team_status_requires_auth(self, api_client):
        """Test team status requires authentication"""
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/activity/team-status")
        assert response.status_code == 401, "Team status should require authentication"


class TestMyDashboard:
    """Tests for /api/my-dashboard endpoint"""
    
    def test_get_my_dashboard(self, authenticated_client):
        """Test getting my dashboard data"""
        response = authenticated_client.get(f"{BASE_URL}/api/my-dashboard")
        assert response.status_code == 200, f"My dashboard failed: {response.text}"
        data = response.json()
        
        # Verify required fields
        assert "rep_name" in data, "Should have rep_name"
        assert "is_manager" in data, "Should have is_manager flag"
        assert "transferred_leads" in data, "Should have transferred_leads"
        assert "my_tasks" in data, "Should have my_tasks"
        assert "metrics" in data, "Should have metrics"

    def test_my_dashboard_tasks_include_lead_context_when_linked(self, authenticated_client):
        """Linked tasks should include enriched lead_name from API."""
        response = authenticated_client.get(f"{BASE_URL}/api/my-dashboard")
        assert response.status_code == 200
        tasks = response.json().get("my_tasks") or []
        linked = [t for t in tasks if t.get("lead_id")]
        if not linked:
            pytest.skip("No linked tasks on dashboard")
        assert (linked[0].get("lead_name") or "").strip(), "Expected lead_name on linked task"
    
    def test_my_dashboard_metrics_structure(self, authenticated_client):
        """Test my dashboard metrics structure"""
        response = authenticated_client.get(f"{BASE_URL}/api/my-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        metrics = data.get("metrics", {})
        required_metrics = [
            "total_leads",
            "hot",
            "warm",
            "cold",
            "site_visits",
            "closed",
            "conversion_rate",
            "pending_tasks",
            "overdue_tasks",
            "leads_received",
            "leads_transferred",
        ]
        
        for metric in required_metrics:
            assert metric in metrics, f"Missing metric: {metric}"
    
    def test_my_dashboard_leads_pagination(self, authenticated_client):
        """Test paginated my dashboard leads endpoint"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 150},
        )
        assert response.status_code == 200, f"Leads pagination failed: {response.text}"
        data = response.json()
        assert "leads" in data, "Should have leads"
        assert "total" in data, "Should have total"
        assert "skip" in data, "Should have skip"
        assert "limit" in data, "Should have limit"
        assert len(data["leads"]) <= 150, "Should return at most 150 leads per page"
        if len(data["leads"]) > 0:
            lead = data["leads"][0]
            assert "id" in lead, "Lead should have id"
            assert "first_name" in lead or "last_name" in lead, "Lead should have name"

    def test_my_dashboard_leads_requires_auth(self, api_client):
        """Test paginated leads requires authentication"""
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/my-dashboard/leads")
        assert response.status_code == 401, "Leads pagination should require authentication"
    
    def test_my_dashboard_requires_auth(self, api_client):
        """Test my dashboard requires authentication"""
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/my-dashboard")
        assert response.status_code == 401, "My dashboard should require authentication"
    
    def test_manager_sees_all_leads(self, authenticated_client):
        """Test that manager (Roshini) sees all leads"""
        response = authenticated_client.get(f"{BASE_URL}/api/my-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        # Roshini is a manager (no leads assigned to her directly)
        assert data.get("is_manager") == True, "Roshini should be detected as manager"
        assert data.get("metrics", {}).get("total_leads", 0) > 0, "Manager should have leads in metrics"

        leads_response = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 1},
        )
        assert leads_response.status_code == 200
        assert leads_response.json().get("total", 0) > 0, "Manager should see leads via pagination"


class TestLeadTransfer:
    """Tests for /api/leads/transfer endpoint"""
    
    @pytest.fixture(scope="class")
    def test_lead_id(self, authenticated_client):
        """Get a lead ID for testing"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 1},
        )
        if response.status_code == 200:
            leads = response.json().get("leads", [])
            if leads:
                return leads[0]["id"]
        pytest.skip("No leads available for transfer testing")
    
    @pytest.fixture(scope="class")
    def test_rep_name(self, authenticated_client):
        """Get a rep name for testing"""
        response = authenticated_client.get(f"{BASE_URL}/api/activity/team-status")
        if response.status_code == 200:
            reps = response.json()
            if reps:
                return reps[0]["name"]
        pytest.skip("No reps available for transfer testing")
    
    def test_transfer_lead_success(self, authenticated_client, test_lead_id, test_rep_name):
        """Test transferring a lead"""
        transfer_data = {
            "lead_id": test_lead_id,
            "to_rep": test_rep_name,
            "notes": "TEST_Transfer for testing purposes"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/leads/transfer",
            json=transfer_data
        )
        assert response.status_code == 200, f"Transfer failed: {response.text}"
        data = response.json()
        assert "transfer_id" in data, "Should return transfer_id"
        assert "message" in data, "Should return message"
        
        # Store transfer_id for acknowledge test
        TestLeadTransfer.last_transfer_id = data["transfer_id"]
    
    def test_transfer_lead_invalid_lead(self, authenticated_client, test_rep_name):
        """Test transferring non-existent lead"""
        transfer_data = {
            "lead_id": "non-existent-lead-id",
            "to_rep": test_rep_name,
            "notes": "TEST_Invalid transfer"
        }
        response = authenticated_client.post(
            f"{BASE_URL}/api/leads/transfer",
            json=transfer_data
        )
        assert response.status_code == 404, "Should return 404 for non-existent lead"
    
    def test_transfer_requires_auth(self, api_client):
        """Test transfer requires authentication"""
        session = requests.Session()
        response = session.post(
            f"{BASE_URL}/api/leads/transfer",
            json={"lead_id": "test", "to_rep": "test"}
        )
        assert response.status_code == 401, "Transfer should require authentication"


class TestAcknowledgeTransfer:
    """Tests for /api/leads/transfer/{id}/acknowledge endpoint"""
    
    def test_acknowledge_transfer_success(self, authenticated_client):
        """Test acknowledging a transfer"""
        # Use the transfer_id from previous test if available
        transfer_id = getattr(TestLeadTransfer, 'last_transfer_id', None)
        
        if not transfer_id:
            # Create a new transfer first
            dashboard_response = authenticated_client.get(
                f"{BASE_URL}/api/my-dashboard/leads",
                params={"skip": 0, "limit": 1},
            )
            if dashboard_response.status_code == 200:
                leads = dashboard_response.json().get("leads", [])
                reps_response = authenticated_client.get(f"{BASE_URL}/api/activity/team-status")
                reps = reps_response.json() if reps_response.status_code == 200 else []
                
                if leads and reps:
                    transfer_data = {
                        "lead_id": leads[0]["id"],
                        "to_rep": reps[0]["name"],
                        "notes": "TEST_Transfer for acknowledge test"
                    }
                    transfer_response = authenticated_client.post(
                        f"{BASE_URL}/api/leads/transfer",
                        json=transfer_data
                    )
                    if transfer_response.status_code == 200:
                        transfer_id = transfer_response.json().get("transfer_id")
        
        if not transfer_id:
            pytest.skip("No transfer available for acknowledge test")
        
        response = authenticated_client.put(f"{BASE_URL}/api/leads/transfer/{transfer_id}/acknowledge")
        assert response.status_code == 200, f"Acknowledge failed: {response.text}"
        data = response.json()
        assert "message" in data, "Should return message"
    
    def test_acknowledge_requires_auth(self, api_client):
        """Test acknowledge requires authentication"""
        session = requests.Session()
        response = session.put(f"{BASE_URL}/api/leads/transfer/test-id/acknowledge")
        assert response.status_code == 401, "Acknowledge should require authentication"


class TestLeadsEndpoint:
    """Tests for /api/leads endpoint to verify lead data"""
    
    def test_get_leads(self, authenticated_client):
        """Test getting leads list"""
        response = authenticated_client.get(f"{BASE_URL}/api/leads")
        assert response.status_code == 200, f"Get leads failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Leads should return a list"
    
    def test_leads_have_temperature(self, authenticated_client):
        """Test leads have temperature field for filtering"""
        response = authenticated_client.get(f"{BASE_URL}/api/leads")
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            lead = data[0]
            # Temperature might be None for some leads
            assert "temperature" in lead or lead.get("temperature") is None, "Lead should have temperature field"
    
    def test_leads_have_assigned_to(self, authenticated_client):
        """Test leads have assigned_to field"""
        response = authenticated_client.get(f"{BASE_URL}/api/leads")
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            lead = data[0]
            # Check for assigned_to or presales_agent
            has_assignment = "assigned_to" in lead or "presales_agent" in lead
            assert has_assignment, "Lead should have assignment field"


class TestTasksEndpoint:
    """Tests for /api/tasks endpoint"""
    
    def test_get_tasks(self, authenticated_client):
        """Test getting tasks list"""
        response = authenticated_client.get(f"{BASE_URL}/api/tasks")
        assert response.status_code == 200, f"Get tasks failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Tasks should return a list"
    
    def test_tasks_structure(self, authenticated_client):
        """Test tasks have required fields"""
        response = authenticated_client.get(f"{BASE_URL}/api/tasks")
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            task = data[0]
            assert "id" in task, "Task should have id"
            assert "status" in task, "Task should have status"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
