#!/usr/bin/env node
/**
 * DocMindAI MCP Server
 * --------------------
 * DocMindAI REST API를 MCP 도구로 노출합니다.
 *
 * 환경 변수:
 *   DOCMIND_API_URL   DocMindAI API 기본 URL (기본: http://localhost:8000)
 *
 * 도구 목록:
 *   docmind_translate            파일을 업로드하고 번역 잡을 시작합니다
 *   docmind_job_status           잡 상태 및 진행률을 조회합니다
 *   docmind_wait_for_completion  잡이 완료될 때까지 폴링합니다
 *   docmind_get_result           완료된 잡의 HTML 결과를 파일로 저장합니다
 *   docmind_list_jobs            최근 잡 목록을 반환합니다
 *   docmind_delete_job           잡을 삭제합니다
 *   docmind_health               API 서버 상태를 확인합니다
 *
 * 사용 예 (Claude Desktop claude_desktop_config.json):
 *   {
 *     "mcpServers": {
 *       "docmindai": {
 *         "command": "node",
 *         "args": ["/path/to/mcp-server/dist/index.js"],
 *         "env": { "DOCMIND_API_URL": "http://localhost:8000" }
 *       }
 *     }
 *   }
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  TextContent,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import * as fs from "node:fs";
import * as path from "node:path";

const API_BASE = (
  process.env.DOCMIND_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

// ---------------------------------------------------------------------------
// 타입
// ---------------------------------------------------------------------------

type Engine =
  | "google"
  | "deepl"
  | "gemini"
  | "openai"
  | "nllb"
  | "nllb-koen"
  | "qwen-0.6b"
  | "lfm2"
  | "lfm2-koen-mt"
  | "yanolja";

type JobStatusValue = "queued" | "processing" | "done" | "error";

interface JobStatus {
  job_id: string;
  status: JobStatusValue;
  progress: number;
  message: string;
  file_name: string;
  source_lang: string;
  target_lang: string;
  engine: string;
  parser_backend: string;
  error?: string;
  created_at: string;
  finished_at?: string;
}

interface JobCreatedResponse {
  job_id: string;
  status: string;
  message: string;
}

interface JobListResponse {
  total: number;
  jobs: JobStatus[];
}

interface HealthResponse {
  status: string;
  version: string;
}

// ---------------------------------------------------------------------------
// API 클라이언트
// ---------------------------------------------------------------------------

async function apiGet<T>(endpoint: string): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GET ${endpoint} 실패 (${res.status}): ${body}`);
  }
  return res.json() as Promise<T>;
}

async function apiDelete(endpoint: string): Promise<void> {
  const res = await fetch(`${API_BASE}${endpoint}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const body = await res.text();
    throw new Error(`DELETE ${endpoint} 실패 (${res.status}): ${body}`);
  }
}

async function apiUploadFile(
  filePath: string,
  params: Record<string, string>
): Promise<JobCreatedResponse> {
  if (!fs.existsSync(filePath)) {
    throw new Error(`파일을 찾을 수 없습니다: ${filePath}`);
  }

  const fileBuffer = fs.readFileSync(filePath);
  const fileName = path.basename(filePath);

  const formData = new FormData();
  formData.append("file", new Blob([fileBuffer]), fileName);
  for (const [key, value] of Object.entries(params)) {
    formData.append(key, value);
  }

  const res = await fetch(`${API_BASE}/api/v1/translate`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`파일 업로드 실패 (${res.status}): ${body}`);
  }
  return res.json() as Promise<JobCreatedResponse>;
}

async function apiDownloadHtml(jobId: string, outputPath: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/result`);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`결과 다운로드 실패 (${res.status}): ${body}`);
  }
  const buffer = await res.arrayBuffer();
  fs.writeFileSync(outputPath, Buffer.from(buffer));
}

// ---------------------------------------------------------------------------
// 폴링 헬퍼
// ---------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollUntilDone(
  jobId: string,
  timeoutMs: number,
  intervalMs: number
): Promise<JobStatus> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await apiGet<JobStatus>(`/api/v1/jobs/${jobId}`);
    if (status.status === "done" || status.status === "error") {
      return status;
    }
    await sleep(Math.min(intervalMs, deadline - Date.now()));
  }
  throw new Error(`잡 ${jobId} 타임아웃 (${timeoutMs / 1000}초 초과)`);
}

// ---------------------------------------------------------------------------
// 도구 정의
// ---------------------------------------------------------------------------

const TOOLS: Tool[] = [
  {
    name: "docmind_translate",
    description:
      "로컬 파일을 DocMindAI API로 업로드하고 번역 잡을 시작합니다. " +
      "지원 형식: PDF, DOCX, PPTX, HWP, HWPX, PNG, JPG, TXT, MD 등. " +
      "반환된 job_id로 docmind_wait_for_completion 또는 docmind_job_status를 호출하세요.",
    inputSchema: {
      type: "object",
      properties: {
        file_path: {
          type: "string",
          description: "번역할 파일의 절대 경로",
        },
        source_lang: {
          type: "string",
          description: "원본 언어 코드 (예: en, ko, ja, zh, fr, de)",
          default: "en",
        },
        target_lang: {
          type: "string",
          description: "번역 대상 언어 코드 (예: ko, en, ja)",
          default: "ko",
        },
        engine: {
          type: "string",
          description:
            "번역 엔진. 내장: google, deepl, gemini, openai, nllb, nllb-koen, " +
            "qwen-0.6b, lfm2, lfm2-koen-mt, yanolja. " +
            "Ollama 로컬 LLM: 'ollama:<모델명>' (예: ollama:llama3.2)",
          default: "google",
        },
        max_workers: {
          type: "string",
          description: "병렬 번역 워커 수 (1–16)",
          default: "4",
        },
        speed_mode: {
          type: "string",
          enum: ["balanced", "fast"],
          description: "Docling 파싱 속도 모드",
          default: "balanced",
        },
        parser_backend: {
          type: "string",
          enum: ["docling", "mineru"],
          description: "문서 파서 백엔드 (mineru는 별도 설치 필요)",
          default: "docling",
        },
      },
      required: ["file_path"],
    },
  },
  {
    name: "docmind_job_status",
    description:
      "번역 잡의 현재 상태와 진행률(0.0–1.0)을 조회합니다. " +
      "status 값: queued | processing | done | error",
    inputSchema: {
      type: "object",
      properties: {
        job_id: {
          type: "string",
          description: "조회할 잡 ID",
        },
      },
      required: ["job_id"],
    },
  },
  {
    name: "docmind_wait_for_completion",
    description:
      "번역 잡이 완료(done 또는 error)될 때까지 주기적으로 폴링합니다. " +
      "완료 시 최종 상태를 반환합니다. 오래 걸리는 문서에 유용합니다.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: {
          type: "string",
          description: "대기할 잡 ID",
        },
        timeout_seconds: {
          type: "number",
          description: "최대 대기 시간 (초, 기본 600)",
          default: 600,
        },
        poll_interval_seconds: {
          type: "number",
          description: "폴링 간격 (초, 기본 3)",
          default: 3,
        },
      },
      required: ["job_id"],
    },
  },
  {
    name: "docmind_get_result",
    description:
      "완료된 잡의 번역 결과를 HTML 파일로 저장합니다. " +
      "이미지가 Base64로 내장된 단일 self-contained HTML입니다. " +
      "브라우저에서 바로 열어볼 수 있습니다.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: {
          type: "string",
          description: "결과를 가져올 잡 ID",
        },
        output_path: {
          type: "string",
          description:
            "저장할 파일 경로 (예: /tmp/result.html). " +
            "생략 시 현재 디렉토리에 {job_id}_result.html 로 저장",
        },
      },
      required: ["job_id"],
    },
  },
  {
    name: "docmind_list_jobs",
    description: "최근 번역 잡 목록을 조회합니다.",
    inputSchema: {
      type: "object",
      properties: {
        limit: {
          type: "number",
          description: "반환할 최대 잡 수 (기본 20, 최대 50)",
          default: 20,
        },
      },
    },
  },
  {
    name: "docmind_delete_job",
    description: "번역 잡 메타데이터를 삭제합니다. 결과 파일은 유지됩니다.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: {
          type: "string",
          description: "삭제할 잡 ID",
        },
      },
      required: ["job_id"],
    },
  },
  {
    name: "docmind_health",
    description: "DocMindAI API 서버 상태를 확인합니다.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
];

// ---------------------------------------------------------------------------
// 핸들러
// ---------------------------------------------------------------------------

async function handleTranslate(args: Record<string, string>): Promise<string> {
  const {
    file_path,
    source_lang = "en",
    target_lang = "ko",
    engine = "google",
    max_workers = "4",
    speed_mode = "balanced",
    parser_backend = "docling",
  } = args;

  const result = await apiUploadFile(file_path, {
    source_lang,
    target_lang,
    engine,
    max_workers,
    speed_mode,
    parser_backend,
  });

  return [
    `잡 생성 완료`,
    `job_id: ${result.job_id}`,
    `상태: ${result.status}`,
    result.message,
    ``,
    `진행 상황 확인: docmind_job_status { "job_id": "${result.job_id}" }`,
    `완료 대기:     docmind_wait_for_completion { "job_id": "${result.job_id}" }`,
  ].join("\n");
}

async function handleJobStatus(args: { job_id: string }): Promise<string> {
  const s = await apiGet<JobStatus>(`/api/v1/jobs/${args.job_id}`);
  const pct = (s.progress * 100).toFixed(1);

  return [
    `job_id:  ${s.job_id}`,
    `상태:    ${s.status} (${pct}%)`,
    `파일:    ${s.file_name}`,
    `언어:    ${s.source_lang} → ${s.target_lang}`,
    `엔진:    ${s.engine}  파서: ${s.parser_backend}`,
    `메시지:  ${s.message}`,
    ...(s.error ? [`오류:    ${s.error}`] : []),
    `생성:    ${s.created_at}`,
    ...(s.finished_at ? [`완료:    ${s.finished_at}`] : []),
  ].join("\n");
}

async function handleWaitForCompletion(args: {
  job_id: string;
  timeout_seconds?: number;
  poll_interval_seconds?: number;
}): Promise<string> {
  const timeoutMs = (args.timeout_seconds ?? 600) * 1000;
  const intervalMs = (args.poll_interval_seconds ?? 3) * 1000;

  const s = await pollUntilDone(args.job_id, timeoutMs, intervalMs);

  if (s.status === "error") {
    return [
      `잡 실패`,
      `job_id: ${s.job_id}`,
      `오류: ${s.error ?? "알 수 없는 오류"}`,
    ].join("\n");
  }

  return [
    `잡 완료`,
    `job_id:  ${s.job_id}`,
    `파일:    ${s.file_name}`,
    `완료:    ${s.finished_at}`,
    ``,
    `결과 저장: docmind_get_result { "job_id": "${s.job_id}" }`,
  ].join("\n");
}

async function handleGetResult(args: {
  job_id: string;
  output_path?: string;
}): Promise<string> {
  const outputPath =
    args.output_path ??
    path.join(process.cwd(), `${args.job_id}_result.html`);

  await apiDownloadHtml(args.job_id, outputPath);

  const stats = fs.statSync(outputPath);
  const sizeKb = (stats.size / 1024).toFixed(1);

  return [
    `결과 저장 완료`,
    `경로: ${outputPath}`,
    `크기: ${sizeKb} KB`,
    `브라우저에서 파일을 열어 번역 결과를 확인하세요.`,
  ].join("\n");
}

async function handleListJobs(args: { limit?: number }): Promise<string> {
  const limit = Math.min(args.limit ?? 20, 50);
  const data = await apiGet<JobListResponse>(`/api/v1/jobs?limit=${limit}`);

  if (data.jobs.length === 0) {
    return "잡이 없습니다.";
  }

  const rows = data.jobs.map((j) => {
    const pct = `${(j.progress * 100).toFixed(0)}%`.padStart(4);
    const status = j.status.toUpperCase().padEnd(10);
    return `[${status}] ${pct}  ${j.job_id}  ${j.source_lang}→${j.target_lang}  ${j.file_name}`;
  });

  return [`총 ${data.total}개 잡`, "", ...rows].join("\n");
}

async function handleDeleteJob(args: { job_id: string }): Promise<string> {
  await apiDelete(`/api/v1/jobs/${args.job_id}`);
  return `잡 ${args.job_id} 삭제 완료`;
}

async function handleHealth(): Promise<string> {
  const data = await apiGet<HealthResponse>("/health");
  return [
    `DocMindAI API 상태: ${data.status}`,
    `버전: ${data.version}`,
    `URL: ${API_BASE}`,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// MCP 서버
// ---------------------------------------------------------------------------

const server = new Server(
  { name: "docmindai", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;

  let text: string;
  let isError = false;

  try {
    switch (name) {
      case "docmind_translate":
        text = await handleTranslate(args as Record<string, string>);
        break;
      case "docmind_job_status":
        text = await handleJobStatus(args as { job_id: string });
        break;
      case "docmind_wait_for_completion":
        text = await handleWaitForCompletion(
          args as {
            job_id: string;
            timeout_seconds?: number;
            poll_interval_seconds?: number;
          }
        );
        break;
      case "docmind_get_result":
        text = await handleGetResult(
          args as { job_id: string; output_path?: string }
        );
        break;
      case "docmind_list_jobs":
        text = await handleListJobs(args as { limit?: number });
        break;
      case "docmind_delete_job":
        text = await handleDeleteJob(args as { job_id: string });
        break;
      case "docmind_health":
        text = await handleHealth();
        break;
      default:
        throw new Error(`알 수 없는 도구: ${name}`);
    }
  } catch (err) {
    text = `오류: ${err instanceof Error ? err.message : String(err)}`;
    isError = true;
  }

  return {
    content: [{ type: "text", text } as TextContent],
    isError,
  };
});

const transport = new StdioServerTransport();
await server.connect(transport);
