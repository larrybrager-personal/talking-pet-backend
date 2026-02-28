const test = require('node:test');
const assert = require('node:assert/strict');
const { proxyJobRequest } = require('../app/api/backend/job/proxy-core.cjs');

function buildRequest({ body, headers = {} }) {
  return {
    headers: {
      get(name) {
        return headers[name.toLowerCase()] ?? null;
      },
    },
    async json() {
      return body;
    },
  };
}

test('forwards upstream JSON errors and preserves request_id', async () => {
  const req = buildRequest({
    body: { prompt: 'hi' },
    headers: { 'x-request-id': 'rid-json-1' },
  });

  const response = await proxyJobRequest({
    request: req,
    backendUrl: 'http://example.test/jobs_prompt_tts',
    fetchImpl: async () => ({
      ok: false,
      status: 500,
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () => JSON.stringify({ message: 'boom', request_id: 'rid-upstream' }),
    }),
    logger: { info() {} },
  });

  assert.equal(response.status, 500);
  assert.equal(response.body.message, 'boom');
  assert.equal(response.body.request_id, 'rid-upstream');
});

test('wraps upstream text errors into JSON with request_id', async () => {
  const req = buildRequest({
    body: { prompt: 'hi' },
    headers: { 'x-request-id': 'rid-text-1' },
  });

  const response = await proxyJobRequest({
    request: req,
    backendUrl: 'http://example.test/jobs_prompt_tts',
    fetchImpl: async () => ({
      ok: false,
      status: 500,
      headers: new Headers({ 'content-type': 'text/plain' }),
      text: async () => 'Internal error token=abc123',
    }),
    logger: { info() {} },
  });

  assert.equal(response.status, 502);
  assert.equal(response.body.message, 'Upstream error');
  assert.equal(response.body.request_id, 'rid-text-1');
  assert.equal(typeof response.body.preview, 'string');
  assert.ok(!response.body.preview.includes('abc123'));
});


test('forwards authorization header to upstream when provided', async () => {
  const req = buildRequest({
    body: { prompt: 'hi' },
    headers: {
      'x-request-id': 'rid-auth-1',
      authorization: 'Bearer client-token',
    },
  });

  let seenHeaders;
  const response = await proxyJobRequest({
    request: req,
    backendUrl: 'http://example.test/jobs_prompt_tts',
    fetchImpl: async (_url, options) => {
      seenHeaders = options.headers;
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => JSON.stringify({ video_url: 'https://example.test/video.mp4' }),
      };
    },
    logger: { info() {} },
  });

  assert.equal(response.status, 200);
  assert.equal(response.body.video_url, 'https://example.test/video.mp4');
  assert.equal(seenHeaders.authorization, 'Bearer client-token');
  assert.equal(seenHeaders['x-request-id'], 'rid-auth-1');
});
