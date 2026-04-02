"""Report generator — produces human-readable processing reports.

Generates both structured (dict) and plain-text reports
from a completed task result.
"""

from datetime import datetime, timezone


def generate_text_report(result: dict) -> str:
    """Generate a plain-text report from a serialized ProcessingResult.

    Args:
        result: Dict with keys: total, found, not_found, errors,
                success_rate, playlist_url, tracks.

    Returns:
        Formatted multi-line string report.
    """
    lines: list[str] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines.append("=" * 60)
    lines.append("  PLAYLIST MIGRATION REPORT")
    lines.append(f"  Generated: {timestamp}")
    lines.append("=" * 60)
    lines.append("")

    # ── Summary ──
    total = result["total"]
    found = result["found"]
    not_found = result["not_found"]
    errors = result["errors"]
    success_rate = result["success_rate"]

    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Total tracks:     {total}")
    lines.append(f"  Found:            {found}")
    lines.append(f"  Not found:        {not_found}")
    lines.append(f"  Errors:           {errors}")
    lines.append(f"  Success rate:     {success_rate:.1f}%")
    lines.append("")

    # ── Playlist URL ──
    playlist_url = result.get("playlist_url")
    if playlist_url:
        lines.append(f"  Playlist URL: {playlist_url}")
        lines.append("")

    # ── Track Details ──
    tracks = result.get("tracks", [])
    if tracks:
        lines.append("TRACK DETAILS")
        lines.append("-" * 40)

        # Group by status
        found_tracks = [t for t in tracks if t["status"] == "found"]
        not_found_tracks = [t for t in tracks if t["status"] == "not_found"]
        error_tracks = [t for t in tracks if t["status"] == "error"]

        if found_tracks:
            lines.append("")
            lines.append(f"  FOUND ({len(found_tracks)}):")
            for t in found_tracks:
                confidence_pct = t["confidence"] * 100
                uri = t.get("platform_uri", "N/A")
                lines.append(
                    f"    [OK]  {t['raw_input']}"
                    f"  (confidence: {confidence_pct:.0f}%, uri: {uri})"
                )

        if not_found_tracks:
            lines.append("")
            lines.append(f"  NOT FOUND ({len(not_found_tracks)}):")
            for t in not_found_tracks:
                confidence_pct = t["confidence"] * 100
                lines.append(
                    f"    [--]  {t['raw_input']}"
                    f"  (best match confidence: {confidence_pct:.0f}%)"
                )

        if error_tracks:
            lines.append("")
            lines.append(f"  ERRORS ({len(error_tracks)}):")
            for t in error_tracks:
                lines.append(f"    [!!]  {t['raw_input']}")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def generate_structured_report(result: dict) -> dict:
    """Enrich a raw task result into a structured report.

    Adds categorized track lists and metadata for API consumers.
    """
    tracks = result.get("tracks", [])

    return {
        "summary": {
            "total": result["total"],
            "found": result["found"],
            "not_found": result["not_found"],
            "errors": result["errors"],
            "success_rate": result["success_rate"],
        },
        "playlist_url": result.get("playlist_url"),
        "tracks": {
            "found": [
                t for t in tracks if t["status"] == "found"
            ],
            "not_found": [
                t for t in tracks if t["status"] == "not_found"
            ],
            "errors": [
                t for t in tracks if t["status"] == "error"
            ],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
