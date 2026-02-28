import { NextResponse } from "next/server";
import proxyCore from "./proxy-core.cjs";

const { proxyJobRequest } = proxyCore;
const UPSTREAM_JOB_URL = `${process.env.BACKEND_BASE_URL || "http://localhost:8000"}/jobs_prompt_tts`;

export async function POST(request) {
  const result = await proxyJobRequest({
    request,
    fetchImpl: fetch,
    backendUrl: UPSTREAM_JOB_URL,
    logger: console,
  });

  return NextResponse.json(result.body, {
    status: result.status,
    headers: {
      "x-request-id": result.requestId,
    },
  });
}
