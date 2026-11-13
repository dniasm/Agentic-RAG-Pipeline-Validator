"""Shared-link visitors. With visitors_can_run off they can view and record human reviews only; with it on
(the current setting) they can do everything."""
import pytest
from fastapi.testclient import TestClient

from validator.api import app
from validator.config import settings

# TestClient's client host is "testclient", which is not loopback, so every request here counts as a visitor.
visitor = TestClient(app)
HOST_ONLY = [("post", "/api/runs/case2/start"), ("post", "/api/runs/case2/stop"), ("post", "/api/runs/case2/reset"),
             ("post", "/api/corpus/ingest"), ("post", "/api/corpus/upload")]


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings, "visitors_can_run", False)


def test_visitor_is_reported_as_remote():
    assert visitor.get("/api/access").json()["remote"] is True


def test_tunnel_header_marks_a_request_remote():
    assert visitor.get("/api/access", headers={"cf-connecting-ip": "203.0.113.5"}).json()["remote"] is True


def test_locked_visitor_cannot_spend_quota_or_change_data(locked):
    assert visitor.get("/api/access").json()["can_run"] is False
    for method, path in HOST_ONLY:
        assert getattr(visitor, method)(path).status_code == 403, path


def test_locked_visitor_may_still_record_human_reviews(locked):
    # Passes the guard; the endpoint itself then validates the body (422), it is not refused (403).
    assert visitor.put("/api/results/case2/Q01/human", json={}).status_code != 403


def test_open_visitor_can_run(monkeypatch):
    monkeypatch.setattr(settings, "visitors_can_run", True)
    assert visitor.get("/api/access").json()["can_run"] is True
    # Not refused by the guard (bodies are invalid on purpose, so nothing actually runs).
    assert visitor.post("/api/runs/case2/reset", json={}).status_code != 403
    assert visitor.post("/api/corpus/upload").status_code != 403
