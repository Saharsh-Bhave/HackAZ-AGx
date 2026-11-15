"""Tests for persistent in-app notifications."""

from pathlib import Path

from driftguard.storage import (
    create_notification,
    get_notifications,
    mark_all_notifications_read,
)


def test_notification_lifecycle(tmp_path: Path) -> None:
    database = tmp_path / "notifications.db"

    created_at = create_notification(
        "Pesticide spraying started",
        "Product is being sprayed under a GO assessment.",
        "success",
        "spray_started",
        database,
    )
    notifications = get_notifications(db_path=database)

    assert len(notifications) == 1
    assert notifications[0]["created_at"] == created_at
    assert notifications[0]["event_type"] == "spray_started"
    assert notifications[0]["is_read"] == 0

    mark_all_notifications_read(database)

    assert get_notifications(db_path=database)[0]["is_read"] == 1


def test_notification_rejects_unknown_level(tmp_path: Path) -> None:
    database = tmp_path / "notifications.db"

    try:
        create_notification("Title", "Message", "critical", "test", database)
    except ValueError as error:
        assert "Unsupported" in str(error)
    else:
        raise AssertionError("Expected an unsupported level to be rejected")
