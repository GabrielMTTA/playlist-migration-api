"""Phase 6 — Playlist Delivery & Report Generation Tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.report_generator import (
    generate_structured_report,
    generate_text_report,
)


# ═══════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════

SAMPLE_RESULT = {
    "total": 5,
    "found": 3,
    "not_found": 1,
    "errors": 1,
    "success_rate": 60.0,
    "playlist_url": "https://open.spotify.com/playlist/abc123",
    "tracks": [
        {
            "raw_input": "Radiohead - Creep",
            "status": "found",
            "platform_id": "id1",
            "platform_uri": "spotify:track:id1",
            "confidence": 0.97,
        },
        {
            "raw_input": "Queen - Bohemian Rhapsody",
            "status": "found",
            "platform_id": "id2",
            "platform_uri": "spotify:track:id2",
            "confidence": 0.92,
        },
        {
            "raw_input": "Nirvana - Smells Like Teen Spirit",
            "status": "found",
            "platform_id": "id3",
            "platform_uri": "spotify:track:id3",
            "confidence": 0.88,
        },
        {
            "raw_input": "Unknown Band - Mystery Song",
            "status": "not_found",
            "platform_id": None,
            "platform_uri": None,
            "confidence": 0.35,
        },
        {
            "raw_input": "Error Track",
            "status": "error",
            "platform_id": None,
            "platform_uri": None,
            "confidence": 0.0,
        },
    ],
}

EMPTY_RESULT = {
    "total": 1,
    "found": 0,
    "not_found": 1,
    "errors": 0,
    "success_rate": 0.0,
    "playlist_url": None,
    "tracks": [
        {
            "raw_input": "Nonexistent",
            "status": "not_found",
            "platform_id": None,
            "platform_uri": None,
            "confidence": 0.20,
        },
    ],
}


# ═══════════════════════════════════════════════════
#  Text Report
# ═══════════════════════════════════════════════════

class TestGenerateTextReport:
    def test_contains_header(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "PLAYLIST MIGRATION REPORT" in report

    def test_contains_summary(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "Total tracks:     5" in report
        assert "Found:            3" in report
        assert "Not found:        1" in report
        assert "Errors:           1" in report
        assert "Success rate:     60.0%" in report

    def test_contains_playlist_url(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "https://open.spotify.com/playlist/abc123" in report

    def test_no_playlist_url_when_none(self) -> None:
        report = generate_text_report(EMPTY_RESULT)
        assert "Playlist URL" not in report

    def test_found_tracks_section(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "FOUND (3):" in report
        assert "[OK]  Radiohead - Creep" in report
        assert "confidence: 97%" in report

    def test_not_found_tracks_section(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "NOT FOUND (1):" in report
        assert "[--]  Unknown Band - Mystery Song" in report

    def test_error_tracks_section(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "ERRORS (1):" in report
        assert "[!!]  Error Track" in report

    def test_contains_timestamp(self) -> None:
        report = generate_text_report(SAMPLE_RESULT)
        assert "Generated:" in report
        assert "UTC" in report

    def test_empty_tracks_graceful(self) -> None:
        result = {**SAMPLE_RESULT, "tracks": []}
        report = generate_text_report(result)
        assert "SUMMARY" in report


# ═══════════════════════════════════════════════════
#  Structured Report
# ═══════════════════════════════════════════════════

class TestGenerateStructuredReport:
    def test_has_summary(self) -> None:
        report = generate_structured_report(SAMPLE_RESULT)
        summary = report["summary"]
        assert summary["total"] == 5
        assert summary["found"] == 3
        assert summary["not_found"] == 1
        assert summary["errors"] == 1
        assert summary["success_rate"] == 60.0

    def test_has_playlist_url(self) -> None:
        report = generate_structured_report(SAMPLE_RESULT)
        assert report["playlist_url"] == "https://open.spotify.com/playlist/abc123"

    def test_tracks_categorized(self) -> None:
        report = generate_structured_report(SAMPLE_RESULT)
        assert len(report["tracks"]["found"]) == 3
        assert len(report["tracks"]["not_found"]) == 1
        assert len(report["tracks"]["errors"]) == 1

    def test_has_generated_at(self) -> None:
        report = generate_structured_report(SAMPLE_RESULT)
        assert "generated_at" in report

    def test_null_playlist_url(self) -> None:
        report = generate_structured_report(EMPTY_RESULT)
        assert report["playlist_url"] is None

    def test_found_tracks_have_uris(self) -> None:
        report = generate_structured_report(SAMPLE_RESULT)
        for t in report["tracks"]["found"]:
            assert t["platform_uri"] is not None
            assert t["platform_uri"].startswith("spotify:track:")


# ═══════════════════════════════════════════════════
#  Report Routes
# ═══════════════════════════════════════════════════

class TestReportRoutes:
    @patch("app.api.routes.playlist.process_playlist")
    def test_json_report_completed(
        self, mock_task: MagicMock, client: TestClient,
    ) -> None:
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = SAMPLE_RESULT
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/abc-123/report")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "tracks" in data
        assert data["summary"]["total"] == 5
        assert len(data["tracks"]["found"]) == 3

    @patch("app.api.routes.playlist.process_playlist")
    def test_text_report_completed(
        self, mock_task: MagicMock, client: TestClient,
    ) -> None:
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = SAMPLE_RESULT
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/abc-123/report/text")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert "PLAYLIST MIGRATION REPORT" in response.text
        assert "Radiohead - Creep" in response.text

    @patch("app.api.routes.playlist.process_playlist")
    def test_report_pending_returns_404(
        self, mock_task: MagicMock, client: TestClient,
    ) -> None:
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/unknown/report")
        assert response.status_code == 404

    @patch("app.api.routes.playlist.process_playlist")
    def test_report_processing_returns_409(
        self, mock_task: MagicMock, client: TestClient,
    ) -> None:
        mock_result = MagicMock()
        mock_result.state = "PROGRESS"
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/in-progress/report")
        assert response.status_code == 409

    @patch("app.api.routes.playlist.process_playlist")
    def test_report_failed_returns_500(
        self, mock_task: MagicMock, client: TestClient,
    ) -> None:
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.info = Exception("boom")
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/failed/report")
        assert response.status_code == 500


# ═══════════════════════════════════════════════════
#  End-to-End Pipeline (mocked)
# ═══════════════════════════════════════════════════

class TestEndToEndPipeline:
    """Simulates the full lifecycle: upload → task → report."""

    @patch("app.api.routes.playlist.process_playlist")
    def test_full_lifecycle(
        self, mock_task: MagicMock, client: TestClient,
    ) -> None:
        # Step 1: Upload file
        mock_task.delay.return_value = MagicMock(id="lifecycle-task-001")

        upload_response = client.post(
            "/api/v1/playlists/upload",
            files={
                "file": (
                    "playlist.txt",
                    b"Radiohead - Creep\nQueen - Bohemian Rhapsody",
                    "text/plain",
                )
            },
            data={"platform": "spotify", "playlist_name": "Test Lifecycle"},
            headers={"Authorization": "Bearer test_token"},
        )
        assert upload_response.status_code == 202
        task_id = upload_response.json()["task_id"]
        assert task_id == "lifecycle-task-001"

        # Step 2: Poll status — processing
        mock_progress = MagicMock()
        mock_progress.state = "PROGRESS"
        mock_progress.info = {"current": 1, "total": 2, "found": 1}
        mock_task.AsyncResult.return_value = mock_progress

        status_response = client.get(f"/api/v1/playlists/tasks/{task_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "processing"

        # Step 3: Poll status — completed
        mock_success = MagicMock()
        mock_success.state = "SUCCESS"
        mock_success.result = SAMPLE_RESULT
        mock_task.AsyncResult.return_value = mock_success

        status_response = client.get(f"/api/v1/playlists/tasks/{task_id}")
        assert status_response.json()["status"] == "completed"

        # Step 4: Get structured report
        report_response = client.get(f"/api/v1/playlists/tasks/{task_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["summary"]["found"] == 3
        assert report["playlist_url"] is not None

        # Step 5: Get text report
        text_response = client.get(
            f"/api/v1/playlists/tasks/{task_id}/report/text"
        )
        assert text_response.status_code == 200
        assert "PLAYLIST MIGRATION REPORT" in text_response.text
        assert "[OK]  Radiohead - Creep" in text_response.text
