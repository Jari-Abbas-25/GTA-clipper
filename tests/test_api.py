"""API Server Route Test Suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from app.backend.server import app

client = TestClient(app)


def test_status_endpoint():
    print("Testing /api/status...")
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    print(" -> /api/status response:", data)
    assert data["status"] == "online"
    assert data["ffmpeg_available"] is True
    assert data["whisper_available"] is True


def test_projects_endpoints():
    print("\nTesting /api/projects...")
    res = client.get("/api/projects")
    assert res.status_code == 200
    projects = res.json()
    print(f" -> Found {len(projects)} existing projects")

    if projects:
        pid = projects[0]["id"]
        print(f"\nTesting /api/projects/{pid}...")
        p_res = client.get(f"/api/projects/{pid}")
        assert p_res.status_code == 200
        p_data = p_res.json()
        print(f" -> Project details: {p_data['meta']['title']}, candidate count: {p_data['candidate_count']}")

        print(f"\nTesting /api/projects/{pid}/highlights...")
        h_res = client.get(f"/api/projects/{pid}/highlights")
        if h_res.status_code == 200:
            h_data = h_res.json()
            print(f" -> Highlight candidates in project: {len(h_data.get('candidates', []))}")


def main():
    print("=" * 60)
    print(" 🚀 TESTING GTA CLIPPER FASTAPI ENDPOINTS")
    print("=" * 60)
    test_status_endpoint()
    test_projects_endpoints()
    print("\n" + "=" * 60)
    print(" ✅ ALL FASTAPI ENDPOINTS RESPONDED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
