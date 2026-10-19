from unittest.mock import patch

from app.services.crm_service import get_crm_route
from app.services.openai_service import qualify_lead

MOCK_AI_RESULT = {
    "lead_score": 85,
    "priority": "Hot",
    "summary": "Acme Inc is seeking AI automation for customer support operations.",
    "recommended_action": "Schedule a demo call with an account executive.",
}

LEAD_PAYLOAD = {
    "name": "John Smith",
    "email": "john@company.com",
    "company": "Acme Inc",
    "message": "We want AI automation for customer support.",
}


# ---------------------------------------------------------------------------
# CRM Routing
# ---------------------------------------------------------------------------

class TestCRMRouting:
    def test_score_80_routes_to_sales_team(self):
        assert get_crm_route(80) == "Sales Team"

    def test_score_95_routes_to_sales_team(self):
        assert get_crm_route(95) == "Sales Team"

    def test_score_50_routes_to_sdr_queue(self):
        assert get_crm_route(50) == "SDR Queue"

    def test_score_65_routes_to_sdr_queue(self):
        assert get_crm_route(65) == "SDR Queue"

    def test_score_49_routes_to_nurture(self):
        assert get_crm_route(49) == "Nurture Campaign"

    def test_score_0_routes_to_nurture(self):
        assert get_crm_route(0) == "Nurture Campaign"


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

class TestWebhookEndpoint:
    def test_lead_submission_returns_201(self, client):
        with patch("app.routes.webhook.qualify_lead", return_value=MOCK_AI_RESULT):
            response = client.post("/webhook/lead", json=LEAD_PAYLOAD)
        assert response.status_code == 201

    def test_lead_submission_response_shape(self, client):
        with patch("app.routes.webhook.qualify_lead", return_value=MOCK_AI_RESULT):
            data = client.post("/webhook/lead", json=LEAD_PAYLOAD).json()
        assert data["status"] == "qualified"
        assert data["lead_id"] == 1
        assert data["analysis"]["lead_score"] == 85
        assert data["analysis"]["priority"] == "Hot"
        assert data["analysis"]["crm_route"] == "Sales Team"

    def test_missing_required_field_returns_422(self, client):
        response = client.post("/webhook/lead", json={"name": "John", "email": "john@x.com"})
        assert response.status_code == 422

    def test_invalid_email_returns_422(self, client):
        payload = {**LEAD_PAYLOAD, "email": "not-an-email"}
        response = client.post("/webhook/lead", json=payload)
        assert response.status_code == 422

    def test_openai_failure_returns_502(self, client):
        with patch("app.routes.webhook.qualify_lead", return_value=None):
            response = client.post("/webhook/lead", json=LEAD_PAYLOAD)
        assert response.status_code == 502


# ---------------------------------------------------------------------------
# Lead retrieval
# ---------------------------------------------------------------------------

class TestLeadRetrieval:
    def test_list_leads_empty_on_fresh_db(self, client):
        data = client.get("/leads").json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_leads_default_pagination_fields(self, client):
        data = client.get("/leads").json()
        assert data["skip"] == 0
        assert data["limit"] == 20

    def test_list_leads_custom_pagination(self, client):
        data = client.get("/leads?skip=5&limit=10").json()
        assert data["skip"] == 5
        assert data["limit"] == 10

    def test_get_unknown_lead_returns_404(self, client):
        assert client.get("/leads/999").status_code == 404

    def test_lead_persisted_after_submission(self, client):
        with patch("app.routes.webhook.qualify_lead", return_value=MOCK_AI_RESULT):
            client.post("/webhook/lead", json=LEAD_PAYLOAD)
        data = client.get("/leads/1").json()
        assert data["name"] == "John Smith"
        assert data["company"] == "Acme Inc"
        assert data["analysis"]["lead_score"] == 85

    def test_list_leads_returns_submitted_lead(self, client):
        with patch("app.routes.webhook.qualify_lead", return_value=MOCK_AI_RESULT):
            client.post("/webhook/lead", json=LEAD_PAYLOAD)
        data = client.get("/leads").json()
        assert data["total"] == 1
        assert data["items"][0]["email"] == "john@company.com"


# ---------------------------------------------------------------------------
# OpenAI service parsing
# ---------------------------------------------------------------------------

class TestOpenAIServiceParsing:
    def test_parses_valid_response(self):
        content = '{"lead_score": 72, "priority": "Warm", "summary": "Test lead.", "recommended_action": "Follow up."}'
        with patch("app.services.openai_service.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value.choices[0].message.content = content
            result = qualify_lead("Jane", "jane@test.com", "TestCo", "Interested in services")
        assert result["lead_score"] == 72
        assert result["priority"] == "Warm"

    def test_clamps_score_above_100(self):
        content = '{"lead_score": 150, "priority": "Hot", "summary": "s", "recommended_action": "a"}'
        with patch("app.services.openai_service.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value.choices[0].message.content = content
            result = qualify_lead("A", "a@b.com", "C", "D")
        assert result["lead_score"] == 100

    def test_returns_none_on_missing_fields(self):
        content = '{"lead_score": 50}'
        with patch("app.services.openai_service.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value.choices[0].message.content = content
            result = qualify_lead("A", "a@b.com", "C", "D")
        assert result is None

    def test_returns_none_on_invalid_json(self):
        content = "not json at all"
        with patch("app.services.openai_service.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value.choices[0].message.content = content
            result = qualify_lead("A", "a@b.com", "C", "D")
        assert result is None
