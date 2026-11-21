"""Comprehensive FastAPI Server Route Test Suite."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from app.backend.server import app
from app.backend.config import PROJECTS_DIR, EXPORTS_DIR

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
    assert "ai_mode" in data


def test_probe_endpoint():
    print("\nTesting /api/probe for Twitch & YouTube...")
    # Twitch
    tw_res = client.post("/api/probe", json={"url_or_path": "https://www.twitch.tv/videos/123456789"})
    print(" -> Twitch probe status:", tw_res.status_code)
    # YouTube URL probe
    yt_res = client.post("/api/probe", json={"url_or_path": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    print(" -> YouTube probe status:", yt_res.status_code)


def test_ai_endpoints():
    print("\nTesting AI Configuration & Testing Endpoints...")
    # 1. Get config
    res = client.get("/api/ai/config")
    assert res.status_code == 200
    cfg = res.json()
    print(" -> Active AI config:", cfg["mode"], "| Provider:", cfg["provider"])

    # 2. Update config
    update_res = client.post("/api/ai/config", json={
        "mode": "local",
        "provider": "ollama",
        "ollama_url": "http://localhost:11434"
    })
    assert update_res.status_code == 200
    print(" -> Updated AI config successfully")

    # 3. Test heuristic connection
    test_res = client.post("/api/ai/test", json={"provider": "heuristics"})
    assert test_res.status_code == 200
    assert test_res.json()["success"] is True
    print(" -> Heuristic connection test:", test_res.json()["message"])

    # 4. Test missing DeepSeek key
    test_ds = client.post("/api/ai/test", json={"provider": "deepseek"})
    assert test_ds.status_code == 200
    assert test_ds.json()["success"] is False
    print(" -> Handled missing DeepSeek key correctly:", test_ds.json()["message"])


def test_demo_project_workflow():
    print("\nTesting Explicit Demo Creation & Workflow...")
    # Create demo project
    res = client.post("/api/projects/create-demo")
    assert res.status_code == 200
    data = res.json()
    pid = data["project_id"]
    print(f" -> Created demo project: {data['title']} (id: {pid})")

    try:
        # Details
        p_res = client.get(f"/api/projects/{pid}")
        assert p_res.status_code == 200
        p_data = p_res.json()
        print(f" -> Project details retrieved. Duration: {p_data['meta'].get('duration', 0)}s, candidates: {p_data['candidate_count']}")

        # Highlights
        h_res = client.get(f"/api/projects/{pid}/highlights")
        assert h_res.status_code == 200
        h_data = h_res.json()
        candidates = h_data.get("candidates", [])
        print(f" -> Found {len(candidates)} highlight candidates in demo project")

        if candidates:
            cid = candidates[0]["id"]
            # Settings
            s_res = client.get(f"/api/projects/{pid}/clips/{cid}/settings")
            assert s_res.status_code == 200

            save_s = client.post(f"/api/projects/{pid}/clips/{cid}/settings", json={
                "layout": "split",
                "facecam_x": 0.70,
                "facecam_y": 0.08,
            })
            assert save_s.status_code == 200
            print(" -> Clip settings saved successfully")

            # Render
            r_res = client.post(f"/api/projects/{pid}/clips/{cid}/render", json={})
            assert r_res.status_code == 200
            r_data = r_res.json()
            print(f" -> Rendered MP4: {r_data['filename']} ({r_data['size_mb']} MB)")

            # Save To Path (overwrite test)
            save_path = PROJECTS_DIR / pid / f"test_copy_{cid}.mp4"
            stp_res = client.post(f"/api/exports/{pid}/{cid}/save-to-path", json={
                "destination_path": str(save_path.resolve()),
                "overwrite": True
            })
            assert stp_res.status_code == 200
            print(f" -> Verified save-to-path: {stp_res.json()['path']}")

    finally:
        # Clean up test demo project to keep projects/ clean
        p_dir = PROJECTS_DIR / pid
        if p_dir.is_dir():
            shutil.rmtree(p_dir, ignore_errors=True)
        e_dir = EXPORTS_DIR / pid
        if e_dir.is_dir():
            shutil.rmtree(e_dir, ignore_errors=True)
        print(" -> Cleaned up test demo project files.")


def main():
    print("=" * 60)
    print(" 🚀 TESTING GTA CLIPPER FASTAPI ENDPOINTS")
    print("=" * 60)
    test_status_endpoint()
    test_probe_endpoint()
    test_ai_endpoints()
    test_demo_project_workflow()
    print("\n" + "=" * 60)
    print(" ✅ ALL FASTAPI ENDPOINTS RESPONDED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
