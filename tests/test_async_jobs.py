import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import main
from fastapi.testclient import TestClient


class AsyncJobsEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_enabled = main.API_AUTH_ENABLED
        main.API_AUTH_ENABLED = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.API_AUTH_ENABLED = self._auth_enabled

    def test_enqueue_prompt_only_returns_202_with_status_url(self):
        with patch("main.create_or_get_async_job", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {
                "id": "job-123",
                "status": "queued",
                "kind": "prompt_only",
                "request_id": "11111111-1111-1111-1111-111111111111",
            }

            response = self.client.post(
                "/async/jobs/prompt_only",
                json={
                    "image_url": "https://example.com/pet.jpg",
                    "prompt": "hello",
                    "request_id": "11111111-1111-1111-1111-111111111111",
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {
                "job_id": "job-123",
                "status": "queued",
                "kind": "prompt_only",
                "request_id": "11111111-1111-1111-1111-111111111111",
                "status_url": "/async/jobs/job-123",
            },
        )

    def test_get_async_job_status_serializes_job_shape(self):
        with patch("main.get_async_job", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "id": "job-123",
                "kind": "prompt_tts",
                "status": "succeeded",
                "endpoint": "/jobs_prompt_tts",
                "request_id": "11111111-1111-1111-1111-111111111111",
                "user_id": "user-1",
                "created_at": "2026-03-16T00:00:00+00:00",
                "updated_at": "2026-03-16T00:01:00+00:00",
                "started_at": "2026-03-16T00:00:10+00:00",
                "completed_at": "2026-03-16T00:00:59+00:00",
                "attempts": 1,
                "max_attempts": 3,
                "response_payload": {"final_url": "https://cdn/final.mp4"},
                "error_payload": None,
            }

            response = self.client.get("/async/jobs/job-123")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_id"], "job-123")
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["response_payload"], {"final_url": "https://cdn/final.mp4"})


class AsyncJobHelpersTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_or_get_async_job_returns_existing_request_match(self):
        existing = {
            "id": "job-existing",
            "status": "processing",
            "kind": "prompt_only",
            "request_id": "11111111-1111-1111-1111-111111111111",
        }
        with (
            patch("main.get_async_job_by_request_id", new_callable=AsyncMock) as mock_get,
            patch("main.create_async_job", new_callable=AsyncMock) as mock_create,
        ):
            mock_get.return_value = existing
            row = await main.create_or_get_async_job(
                kind=main.AsyncJobKind.prompt_only,
                endpoint_name="/jobs_prompt_only",
                payload={"prompt": "hello"},
                user_id=None,
                request_id="11111111-1111-1111-1111-111111111111",
            )

        self.assertEqual(row, existing)
        mock_create.assert_not_awaited()


class AsyncJobTimeoutBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_fail_expired_async_jobs_marks_old_queued_job_failed(self):
        old_job = {
            "id": "job-queued-old",
            "status": "queued",
            "created_at": "2026-03-16T00:00:00+00:00",
            "attempts": 0,
        }

        with (
            patch("main.ASYNC_JOB_MAX_QUEUED_AGE_SEC", 60),
            patch("main.list_async_jobs", new_callable=AsyncMock) as mock_list,
            patch("main.update_async_job", new_callable=AsyncMock) as mock_update,
            patch("main.datetime") as mock_datetime,
        ):
            mock_list.return_value = [old_job]
            mock_datetime.now.return_value = datetime(2026, 3, 16, 0, 2, 0, tzinfo=timezone.utc)
            mock_datetime.fromisoformat.side_effect = datetime.fromisoformat

            expired = await main.fail_expired_async_jobs()

        self.assertEqual(expired, 1)
        mock_update.assert_awaited_once()
        update_kwargs = mock_update.await_args.kwargs
        self.assertEqual(update_kwargs["status"], main.AsyncJobStatus.failed)
        self.assertEqual(update_kwargs["error_payload"]["reason"], "queued_timeout")
        self.assertTrue(update_kwargs["error_payload"]["retryable"])

    async def test_fail_expired_async_jobs_marks_old_processing_job_failed(self):
        old_job = {
            "id": "job-processing-old",
            "status": "processing",
            "created_at": "2026-03-16T00:00:00+00:00",
            "started_at": "2026-03-16T00:01:00+00:00",
            "locked_at": "2026-03-16T00:01:00+00:00",
            "attempts": 1,
            "locked_by": "worker-1",
        }

        with (
            patch("main.ASYNC_JOB_MAX_PROCESSING_AGE_SEC", 60),
            patch("main.list_async_jobs", new_callable=AsyncMock) as mock_list,
            patch("main.update_async_job", new_callable=AsyncMock) as mock_update,
            patch("main.datetime") as mock_datetime,
        ):
            mock_list.return_value = [old_job]
            mock_datetime.now.return_value = datetime(2026, 3, 16, 0, 3, 0, tzinfo=timezone.utc)
            mock_datetime.fromisoformat.side_effect = datetime.fromisoformat

            expired = await main.fail_expired_async_jobs()

        self.assertEqual(expired, 1)
        mock_update.assert_awaited_once()
        update_kwargs = mock_update.await_args.kwargs
        self.assertEqual(update_kwargs["status"], main.AsyncJobStatus.failed)
        self.assertEqual(update_kwargs["error_payload"]["reason"], "processing_timeout")
        self.assertEqual(update_kwargs["attempts"], 1)


class AsyncWorkerBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_worker_claims_and_completes_prompt_only_job(self):
        claimed_job = {
            "id": "job-123",
            "kind": "prompt_only",
            "status": "processing",
            "locked_at": "2026-03-16T00:00:10+00:00",
            "attempts": 1,
            "request_payload": {
                "image_url": "https://example.com/pet.jpg",
                "prompt": "hello",
                "request_id": "11111111-1111-1111-1111-111111111111",
            },
        }

        with (
            patch("main.claim_next_async_job", new_callable=AsyncMock) as mock_claim,
            patch("main.process_prompt_only_request", new_callable=AsyncMock) as mock_process,
            patch("main.update_async_job", new_callable=AsyncMock) as mock_update,
        ):
            mock_claim.side_effect = [claimed_job, None]
            mock_process.return_value = {
                "video_url": "https://provider/video.mp4",
                "final_url": "https://cdn/final.mp4",
            }

            result = await main.run_async_worker_once(worker_id="worker-test", limit=2)

        self.assertEqual([row["id"] for row in result], ["job-123"])
        mock_process.assert_awaited()
        processed_req = mock_process.await_args.args[0]
        self.assertIsNone(processed_req.request_id)
        mock_update.assert_awaited()
        update_kwargs = mock_update.await_args.kwargs
        self.assertEqual(update_kwargs["status"], main.AsyncJobStatus.succeeded)
        self.assertEqual(
            update_kwargs["response_payload"],
            {
                "video_url": "https://provider/video.mp4",
                "final_url": "https://cdn/final.mp4",
            },
        )


if __name__ == "__main__":
    unittest.main()
