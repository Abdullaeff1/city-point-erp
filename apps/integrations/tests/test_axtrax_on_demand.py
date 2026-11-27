"""Səhifə açılışında AxTrax on-demand sync — throttle və fail-soft."""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "axtrax-on-demand-tests",
        }
    }
)
class AxTraxOnDemandTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_skips_without_password(self):
        from apps.integrations.axtrax_on_demand import maybe_refresh_axtrax_from_view

        with patch.dict(
            "os.environ",
            {
                "AXTRAX_SYNC_ON_VIEW": "1",
                "AXTRAX_SYNC_ON_VIEW_ALLOW_LIVE": "1",
                "TURNSTILE_MSSQL_PASSWORD": "",
            },
            clear=False,
        ):
            result = maybe_refresh_axtrax_from_view()
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "no_password")
        self.assertFalse(result["attempted"])

    def test_disabled_via_env(self):
        from apps.integrations.axtrax_on_demand import maybe_refresh_axtrax_from_view

        with patch.dict(
            "os.environ",
            {
                "AXTRAX_SYNC_ON_VIEW": "0",
                "AXTRAX_SYNC_ON_VIEW_ALLOW_LIVE": "1",
                "TURNSTILE_MSSQL_PASSWORD": "secret",
            },
            clear=False,
        ):
            result = maybe_refresh_axtrax_from_view()
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")

    def test_successful_sync_and_throttle(self):
        from apps.integrations.axtrax_on_demand import maybe_refresh_axtrax_from_view

        env = {
            "AXTRAX_SYNC_ON_VIEW": "1",
            "AXTRAX_SYNC_ON_VIEW_ALLOW_LIVE": "1",
            "AXTRAX_SYNC_ON_VIEW_INTERVAL": "60",
            "TURNSTILE_MSSQL_PASSWORD": "secret",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "apps.integrations.axtrax_health.axtrax_sync_health",
            return_value={"last_people_sync_at": object(), "events_stale": False},
        ), patch(
            "apps.integrations.axtrax_events_sync.get_events_cursor", return_value=10
        ), patch(
            "apps.integrations.axtrax_mssql.fetch_granted_events", return_value=[]
        ), patch(
            "apps.integrations.axtrax_events_sync.sync_event_rows"
        ) as sync_rows, patch(
            "apps.integrations.axtrax_people_sync.sync_people_from_mssql"
        ) as sync_people:
            first = maybe_refresh_axtrax_from_view(include_people=False)
            second = maybe_refresh_axtrax_from_view(include_people=False)

        self.assertTrue(first["synced"])
        self.assertEqual(first["reason"], "ok")
        sync_rows.assert_not_called()
        sync_people.assert_not_called()
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "throttled")

    def test_connection_error_is_soft(self):
        from apps.integrations.axtrax_on_demand import maybe_refresh_axtrax_from_view

        with patch.dict(
            "os.environ",
            {
                "AXTRAX_SYNC_ON_VIEW": "1",
                "AXTRAX_SYNC_ON_VIEW_ALLOW_LIVE": "1",
                "TURNSTILE_MSSQL_PASSWORD": "secret",
            },
            clear=False,
        ), patch(
            "apps.integrations.axtrax_health.axtrax_sync_health",
            return_value={"last_people_sync_at": None, "events_stale": True},
        ), patch(
            "apps.integrations.axtrax_people_sync.sync_people_from_mssql",
            side_effect=RuntimeError("people down"),
        ), patch(
            "apps.integrations.axtrax_events_sync.get_events_cursor", return_value=0
        ), patch(
            "apps.integrations.axtrax_mssql.fetch_granted_events",
            side_effect=RuntimeError("TDS unavailable"),
        ):
            result = maybe_refresh_axtrax_from_view()

        self.assertTrue(result["attempted"])
        self.assertFalse(result["synced"])
        self.assertEqual(result["reason"], "error")
        self.assertIn("qoşulmaq", result["message"])
