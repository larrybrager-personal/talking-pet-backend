/**
 * Proxy helpers for /api/backend/job.
 * Keeps error responses JSON-shaped and request_id-correlated.
 */

const MAX_PREVIEW_CHARS = 280;

function sanitizePreview(input) {
  if (!input) return "";
  const compact = String(input).replace(/[\r\n\t]+/g, " ").replace(/\s{2,}/g, " ").trim();
  const redactedHeaders = compact
    .replace(/(authorization\s*[:=]\s*)([^\s,;]+)/gi, "$1[redacted]")
    .replace(/(bearer\s+)([a-z0-9\-._~+/=]+)/gi, "$1[redacted]")
    .replace(/((?:api[_-]?key|token|password|secret)\s*[:=]\s*)([^\s,;]+)/gi, "$1[redacted]");
  if (redactedHeaders.length <= MAX_PREVIEW_CHARS) return redactedHeaders;
  return `${redactedHeaders.slice(0, MAX_PREVIEW_CHARS)}…`;
}

function maybeParseJson(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function getRequestIdFromHeaders(headers) {
  return headers?.get?.("x-request-id") || headers?.get?.("x-correlation-id") || null;
}

function ensureRequestId(candidate) {
  if (candidate && String(candidate).trim()) return String(candidate).trim();
  return crypto.randomUUID();
}

function buildUpstreamHeaders(requestHeaders, requestId) {
  const authHeader = requestHeaders?.get?.("authorization");
  const headers = {
    "content-type": "application/json",
    "x-request-id": requestId,
  };
  if (authHeader && String(authHeader).trim()) {
    headers.authorization = String(authHeader).trim();
  }
  return headers;
}

function buildUpstreamNonJsonError(statusCode, requestId, bodyText) {
  const mappedStatus = statusCode >= 500 ? 502 : 500;
  return {
    status: mappedStatus,
    body: {
      request_id: requestId,
      status: mappedStatus,
      message: "Upstream error",
      preview: sanitizePreview(bodyText),
    },
  };
}

async function proxyJobRequest({ request, fetchImpl, backendUrl, logger = console }) {
  const requestId = ensureRequestId(getRequestIdFromHeaders(request.headers));

  let payload;
  try {
    payload = await request.json();
  } catch {
    return {
      requestId,
      status: 400,
      body: { request_id: requestId, status: 400, message: "Invalid JSON body" },
    };
  }

  let upstream;
  try {
    upstream = await fetchImpl(backendUrl, {
      method: "POST",
      headers: buildUpstreamHeaders(request.headers, requestId),
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      requestId,
      status: 500,
      body: {
        request_id: requestId,
        status: 500,
        message: "Upstream error",
        preview: "Failed to connect to upstream",
      },
    };
  }

  const responseText = await upstream.text();
  const preview = sanitizePreview(responseText);
  logger.info?.("proxy_upstream_response", {
    request_id: requestId,
    upstream_status: upstream.status,
    preview,
  });

  const parsedJson = maybeParseJson(responseText);
  const contentType = upstream.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json") || parsedJson !== null;

  if (!upstream.ok) {
    if (isJson && parsedJson && typeof parsedJson === "object") {
      return {
        requestId,
        status: upstream.status,
        body: {
          ...parsedJson,
          request_id: parsedJson.request_id || requestId,
        },
      };
    }
    const err = buildUpstreamNonJsonError(upstream.status, requestId, responseText);
    return { requestId, ...err };
  }

  if (isJson && parsedJson && typeof parsedJson === "object") {
    return {
      requestId,
      status: upstream.status,
      body: {
        ...parsedJson,
        request_id: parsedJson.request_id || requestId,
      },
    };
  }

  return {
    requestId,
    status: 200,
    body: {
      request_id: requestId,
      status: 200,
      message: "Upstream success",
      preview,
    },
  };
}

module.exports = {
  proxyJobRequest,
  sanitizePreview,
  ensureRequestId,
};
