"""Timezone-aware conversation dates must be normalized to local before use.

The store is naive-local throughout: ``add_conversation``, the index writers and
every importer use a bare ``datetime.now()``, and ``generate_weekly_summary``
windows against a local ``today``. But ``_resolve_conversation_date`` accepts ISO
strings from outside — including the ``Z`` form it explicitly rewrites — so an
import can hand it a timezone-aware value.

Left aware, that value files the conversation under the *source's* calendar day
and then vanishes from the user's week whenever the two disagree. For a UTC
source and an EDT user that is every conversation after 20:00 local, which is not
an edge case.

These tests deliberately do NOT use "now" for the shifting case. #218 fixed the
weekly-summary tests by stamping fixtures in local time, which was correct for
those tests but left this path unexercised — a bug that only reproduces for four
hours a week is not one to leave to the clock. The offset here is chosen so the
calendar day is guaranteed to differ, whatever zone the suite runs in.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conversation_memory import ConversationMemoryServer


def _date_shifted_timestamp(local_now: datetime) -> datetime:
    """Return ``local_now`` as an aware value whose calendar day differs.

    +14 and -11 are 25 hours apart, so at least one of them must land on a
    different date from local — no dependence on what time the suite runs.
    """
    for hours in (14, -11):
        stamped = local_now.astimezone().astimezone(timezone(timedelta(hours=hours)))
        if stamped.date() != local_now.date():
            return stamped
    pytest.fail("could not construct a date-shifted timestamp")
    raise AssertionError  # unreachable; keeps type checkers happy


class TestResolveConversationDate:
    def test_aware_input_becomes_naive_local(self):
        aware = datetime(2026, 8, 17, 1, 30, tzinfo=timezone.utc)
        got = ConversationMemoryServer._resolve_conversation_date(aware.isoformat())

        assert got.tzinfo is None, "an aware value would compare against a local window"
        assert got == aware.astimezone().replace(tzinfo=None)

    def test_z_suffix_is_handled_like_an_offset(self):
        got = ConversationMemoryServer._resolve_conversation_date("2026-08-17T01:30:00Z")
        expected = datetime(2026, 8, 17, 1, 30, tzinfo=timezone.utc).astimezone()

        assert got.tzinfo is None
        assert got == expected.replace(tzinfo=None)

    def test_naive_input_is_passed_through_untouched(self):
        """Naive is already local; assuming a zone would shift existing records."""
        naive = datetime(2026, 8, 16, 21, 30)
        got = ConversationMemoryServer._resolve_conversation_date(naive.isoformat())

        assert got == naive
        assert got.tzinfo is None

    @pytest.mark.parametrize("bad", ["", None, "not-a-date", "2026-13-45T99:99:99"])
    def test_absent_or_malformed_falls_back_to_now(self, bad):
        before = datetime.now()
        got = ConversationMemoryServer._resolve_conversation_date(bad)

        assert got.tzinfo is None
        assert before <= got <= datetime.now()


class TestWeeklySummaryAcrossZones:
    def test_conversation_stamped_in_another_zone_lands_in_the_local_week(self, tmp_path):
        """The user's week is the user's, whatever zone the source stamped in."""
        server = ConversationMemoryServer(str(tmp_path), use_data_dir=True, enable_sqlite=False)
        local_now = datetime.now()
        stamped = _date_shifted_timestamp(local_now)
        assert stamped.date() != local_now.date(), "precondition: the fixture must shift the day"

        import asyncio

        asyncio.run(server.add_conversation("body text", "Cross-zone import", stamped.isoformat()))
        summary = asyncio.run(server.generate_weekly_summary())

        assert "Cross-zone import" in summary, (
            f"a conversation stamped {stamped.isoformat()} (same instant as local "
            f"{local_now:%Y-%m-%d %H:%M}) fell outside the local week"
        )

    def test_it_is_filed_under_the_local_day_not_the_source_day(self, tmp_path):
        server = ConversationMemoryServer(str(tmp_path), use_data_dir=True, enable_sqlite=False)
        local_now = datetime.now()
        stamped = _date_shifted_timestamp(local_now)

        import asyncio

        result = asyncio.run(
            server.add_conversation("body text", "Cross-zone import", stamped.isoformat())
        )

        # The month folder follows local, so a late-evening import does not
        # jump into next month's directory on the last day of the month.
        # Path.parts, not split("/"): the separator is "\\" on Windows, which is
        # the exact assumption CLAUDE.md warns about — and this line originally
        # made it, so the required Windows check earned its keep here.
        parts = Path(result["file_path"]).parts
        assert f"{local_now:%Y}" in parts
        assert any(f"{local_now:%m}" in part for part in parts)
