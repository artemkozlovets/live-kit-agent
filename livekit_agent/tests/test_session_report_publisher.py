import pytest


@pytest.mark.asyncio
async def test_session_report_publisher_posts_report_with_auth_header() -> None:
    sent: dict[str, object] = {}

    async def post_json(url: str, payload: dict, headers: dict) -> dict:
        sent["url"] = url
        sent["payload"] = payload
        sent["headers"] = headers
        return {"ok": True}

    class _Room:
        name = "room-123"

    class _Report:
        def to_dict(self) -> dict:
            return {"hello": "world"}

    class _Ctx:
        room = _Room()

        def make_session_report(self) -> _Report:
            return _Report()

    from livekit_agent.session_report_publisher import SessionReportPublisher

    publisher = SessionReportPublisher(
        reports_url="https://example.test/observability/session-report",
        token="secret-token",
        post_json=post_json,
    )

    await publisher.publish(_Ctx())

    assert sent["url"] == "https://example.test/observability/session-report"
    assert sent["payload"] == {"room_name": "room-123", "report": {"hello": "world"}}
    assert sent["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer secret-token",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_session_report_publisher_noops_when_no_url() -> None:
    called = False

    async def post_json(_: str, __: dict, ___: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    class _Room:
        name = "room-123"

    class _Report:
        def to_dict(self) -> dict:
            return {"hello": "world"}

    class _Ctx:
        room = _Room()

        def make_session_report(self) -> _Report:
            return _Report()

    from livekit_agent.session_report_publisher import SessionReportPublisher

    publisher = SessionReportPublisher(reports_url="", token=None, post_json=post_json)
    await publisher.publish(_Ctx())
    assert called is False


@pytest.mark.asyncio
async def test_session_report_publisher_swallows_publish_errors() -> None:
    async def post_json(_: str, __: dict, ___: dict) -> dict:
        raise RuntimeError("boom")

    class _Room:
        name = "room-123"

    class _Report:
        def to_dict(self) -> dict:
            return {"hello": "world"}

    class _Ctx:
        room = _Room()

        def make_session_report(self) -> _Report:
            return _Report()

    from livekit_agent.session_report_publisher import SessionReportPublisher

    publisher = SessionReportPublisher(
        reports_url="https://example.test/observability/session-report",
        token=None,
        post_json=post_json,
    )

    # Should not raise.
    await publisher.publish(_Ctx())

