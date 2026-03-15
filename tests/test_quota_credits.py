import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main


class CreditCostTestCase(unittest.TestCase):
    def test_credit_cost_maps_from_model_quality_lane(self):
        self.assertEqual(main.get_credit_cost_for_model('bytedance/seedance-1-pro-fast'), 1)
        self.assertEqual(main.get_credit_cost_for_model('wan-video/wan2.6-i2v-flash'), 2)
        self.assertEqual(main.get_credit_cost_for_model('wan-video/wan-2.6-i2v'), 4)
        self.assertEqual(main.get_credit_cost_for_model('kwaivgi/kling-v2.6'), 8)


class QuotaPeriodTestCase(unittest.TestCase):
    def test_monthly_period_starts_at_utc_month_boundary(self):
        sample = main.datetime(2026, 3, 15, 19, 4, tzinfo=main.timezone.utc)
        period_start = main.get_usage_period_start('monthly', sample)
        self.assertEqual(period_start.isoformat(), '2026-03-01T00:00:00+00:00')


class EnforceGenerationQuotaTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_when_remaining_credits_are_insufficient(self):
        user_context = main.UserContext(id='00000000-0000-0000-0000-000000000000', plan_tier='creator')
        with patch('main.get_used_credits_for_period', new_callable=AsyncMock) as mock_usage:
            mock_usage.return_value = {
                'used': 29,
                'limit': 30,
                'remaining': 1,
                'period': 'monthly',
                'period_start': '2026-03-01T00:00:00+00:00',
            }
            with self.assertRaises(main.HTTPException) as exc:
                await main.enforce_generation_quota(
                    user_context=user_context,
                    model='kwaivgi/kling-v2.6',
                    plan_tier='creator',
                )

        self.assertEqual(exc.exception.status_code, 403)
        self.assertIn('requires 8 credit', str(exc.exception.detail))

    async def test_allows_when_remaining_credits_cover_request(self):
        user_context = main.UserContext(id='00000000-0000-0000-0000-000000000000', plan_tier='studio')
        with patch('main.get_used_credits_for_period', new_callable=AsyncMock) as mock_usage:
            mock_usage.return_value = {
                'used': 20,
                'limit': 120,
                'remaining': 100,
                'period': 'monthly',
                'period_start': '2026-03-01T00:00:00+00:00',
            }
            result = await main.enforce_generation_quota(
                user_context=user_context,
                model='kwaivgi/kling-v2.6',
                plan_tier='studio',
            )

        self.assertEqual(result['required'], 8)
        self.assertEqual(result['remaining'], 100)


class QuotaSummaryEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_returns_weighted_credit_summary_for_user(self):
        with patch('main.resolve_plan_tier', new_callable=AsyncMock) as mock_tier, patch(
            'main.get_used_credits_for_period', new_callable=AsyncMock
        ) as mock_usage:
            mock_tier.return_value = 'creator'
            mock_usage.return_value = {
                'used': 8,
                'limit': 30,
                'remaining': 22,
                'period': 'monthly',
                'period_start': '2026-03-01T00:00:00+00:00',
            }

            response = self.client.post(
                '/quota_summary',
                json={
                    'user_context': {
                        'id': '00000000-0000-0000-0000-000000000000',
                        'plan_tier': 'creator',
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'used': 8,
                'limit': 30,
                'remaining': 22,
                'period': 'monthly',
                'period_start': '2026-03-01T00:00:00+00:00',
                'plan_tier': 'creator',
                'unit': 'credits',
            },
        )
        mock_tier.assert_awaited_once()
        mock_usage.assert_awaited_once_with(
            user_id='00000000-0000-0000-0000-000000000000',
            plan_tier='creator',
        )

    def test_rejects_invalid_user_uuid(self):
        response = self.client.post(
            '/quota_summary',
            json={
                'user_context': {
                    'id': 'not-a-uuid',
                    'plan_tier': 'creator',
                }
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'user_context.id must be a valid UUID')


if __name__ == '__main__':
    unittest.main()
