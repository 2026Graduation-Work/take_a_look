// 보유 화면 캡처의 글자 읽기. 사용자 브라우저(웹 워커) 안에서만 돌고 이미지는 어디에도 보내지 않는다.
// 엔진: PaddleOCR.js 0.4.2(Apache-2.0)의 워커 파일 + PP-OCRv5 검출 + 한국어 인식(korean_PP-OCRv5_mobile_rec).
// - 워커 파일(OpenCV, ONNX Runtime이 들어 있는 완성본, 약 11MB), wasm, 모델(검출 4.8MB + 한국어 인식 13.5MB)은
//   빌드 때 고정 판을 sha256으로 확인해 public/ocr/에 둔다(scripts/fetch-ocr-assets.mjs). 우리 사이트에서 주므로
//   어느 화면에서 들어와도(문서를 새로 열지 않은 화면 이동 포함) 화면 CSP에 막히지 않는다.
// - 패키지를 번들에 넣으면 Turbopack이 워커를 다시 묶다 실패하고, 메인 화면에도 OpenCV 10MB가 실린다.
//   그래서 패키지와 같은 통신 규약(worker-transport-request/response)으로 워커에 직접 말을 건다.
// 모두 '캡처로 불러오기'를 처음 누를 때만 받는다.
// - 파일 경로에 판(/ocr/v1/)을 넣고 1년 immutable 캐시를 건다(next.config.ts). 판을 올리면 v2로 옮긴다.
//   1단계 % 막대는 같은 주소를 화면 쪽에서 먼저 받아 세고(prefetch), 워커는 그 캐시에서 바로 읽는다.

import { STORAGE_KEYS } from "../storage-keys.ts";

export interface OcrLine {
  text: string;
  score: number; // 0~1 인식 확신
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const ASSETS = "/ocr/v1/"; // 워커, wasm, 모델(워커 안에서 같은 출처로 풀린다)
const SDK = `${ASSETS}worker-entry-C9UNuyOJ.js`;
// 워커가 받는 파일과 크기(scripts/fetch-ocr-assets.mjs와 같은 판). 압축 전송이면 Content-Length가 없어 크기를 여기 둔다
const FILES: [string, number][] = [
  ["worker-entry-C9UNuyOJ.js", 11_341_486],
  ["ort-wasm-simd-threaded.jsep.mjs", 46_595],
  ["ort-wasm-simd-threaded.jsep.wasm", 25_014_754],
  ["PP-OCRv5_mobile_det_onnx_infer.tar", 4_843_520],
  ["korean_PP-OCRv5_mobile_rec_onnx_infer.tar", 13_537_280],
];
export const TOOL_BYTES = FILES.reduce((sum, [, size]) => sum + size, 0);
const DARK_LUMA = 0.45; // 평균 밝기가 이보다 어두우면 뒤집어 읽는다(어두운 화면)
const MIN_WIDTH = 1000; // 이보다 좁은 캡처는 키워서 읽는다(작은 글자)

// PaddleOCR.create({ textDetectionModelName, textRecognitionModelName, textRecognitionModelAsset, worker: true })가
// 워커에 보내는 init 값과 같다(0.4.2 기준, 문서 밖 기능인 문서 보정, 글줄 방향은 뺐다).
const DET = { text_det_limit_side_len: 64, text_det_limit_type: "min", text_det_max_side_limit: 4000, text_det_thresh: 0.3, text_det_box_thresh: 0.6, text_det_unclip_ratio: 1.5, text_rec_score_thresh: 0 };
const INIT = {
  options: {
    pipelineConfig: {
      pipelineName: "OCR",
      raw: {
        pipeline_name: "OCR",
        text_type: "general",
        use_doc_preprocessor: false,
        use_textline_orientation: false,
        SubModules: {
          TextDetection: { module_name: "text_detection", model_name: "PP-OCRv5_mobile_det", model_dir: null, limit_side_len: 64, limit_type: "min", max_side_limit: 4000, thresh: 0.3, box_thresh: 0.6, unclip_ratio: 1.5 },
          TextRecognition: { module_name: "text_recognition", model_name: "korean_PP-OCRv5_mobile_rec", model_dir: null, batch_size: 6, score_thresh: 0 },
        },
      },
      warnings: [],
      unsupportedFeatures: [],
      modelSelection: { textDetectionModelName: "PP-OCRv5_mobile_det", textRecognitionModelName: "korean_PP-OCRv5_mobile_rec" },
      assets: {
        det: { url: `${ASSETS}PP-OCRv5_mobile_det_onnx_infer.tar` },
        rec: { url: `${ASSETS}korean_PP-OCRv5_mobile_rec_onnx_infer.tar` },
      },
      runtimeDefaults: DET,
      pipelineBatchSize: 1,
      textDetectionBatchSize: 1,
      textRecognitionBatchSize: 6,
    },
    ortOptions: { backend: "wasm", wasmPaths: ASSETS, disableWasmProxy: true },
  },
};

type Response = { kind: string; status: "success" | "error"; requestId: number; payload?: unknown; error?: { message: string } };

let worker: Worker | null = null;
let ready: Promise<unknown> | null = null;
let loaded = false; // 이 탭에서 읽는 도구를 이미 받았는지(화면이 '내려받는 중'을 따로 보인다)
let nextId = 1;
const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();

function request(type: string, payload: unknown, transfer: Transferable[] = []): Promise<unknown> {
  if (!worker) {
    // 같은 출처 파일로 바로 만든다. 워커는 /ocr/ 응답의 CSP('unsafe-eval' 허용, next.config.ts)를 받는다
    worker = new Worker(SDK, { type: "module" });
    worker.onmessage = ({ data }: MessageEvent<Response>) => {
      const job = pending.get(data?.requestId);
      if (data?.kind !== "worker-transport-response" || !job) return;
      pending.delete(data.requestId);
      if (data.status === "success") job.resolve(data.payload);
      else job.reject(new Error(data.error?.message ?? "글자를 읽지 못했어요."));
    };
    worker.onerror = (event) => {
      for (const job of pending.values()) job.reject(new Error(event.message || "글자 읽기 도구를 불러오지 못했어요."));
      pending.clear();
      worker?.terminate();
      worker = null;
      ready = null;
      loaded = false;
    };
  }
  const requestId = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    worker!.postMessage({ kind: "worker-transport-request", type, payload, requestId }, transfer);
  });
}

// 이 탭에서 이미 받았거나, 이 브라우저 캐시에 받아 둔 적이 있으면 1단계를 건너뛴다
export function toolCached(): boolean {
  if (loaded) return true;
  try {
    return window.localStorage.getItem(STORAGE_KEYS.ocrAssets) !== null;
  } catch {
    return false;
  }
}

// 1단계: 워커가 받을 파일을 같은 주소로 먼저 받아 받은 바이트를 센다(내용은 버리고 브라우저 캐시에만 남는다)
export async function prefetch(onProgress: (received: number) => void, signal: AbortSignal): Promise<void> {
  let received = 0;
  await Promise.all(FILES.map(async ([name]) => {
    const response = await fetch(`${ASSETS}${name}`, { signal });
    if (!response.ok || !response.body) throw new Error(`${response.status}: ${name}`);
    const reader = response.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      received += value.byteLength;
      onProgress(received);
    }
  }));
}

// 취소: 워커를 끝내고 기다리던 요청을 모두 실패로 돌린다. 다음 불러오기는 처음부터 다시 만든다
export function cancel(): void {
  worker?.terminate();
  worker = null;
  ready = null;
  loaded = false;
  for (const job of pending.values()) job.reject(new Error("취소했어요."));
  pending.clear();
}

export function init(): Promise<unknown> {
  ready ??= request("init", INIT).then((value) => {
    loaded = true;
    try {
      window.localStorage.setItem(STORAGE_KEYS.ocrAssets, new Date().toISOString());
    } catch {
      // 저장이 막혀도 이 탭에서는 loaded로 건너뛴다
    }
    return value;
  }, (error: unknown) => {
    ready = null; // 받기에 실패하면 다음 시도에서 다시 받는다
    throw error;
  });
  return ready;
}

// 어두우면 밝기를 뒤집고, 좁으면 키운다. 전처리 규칙은 이 두 가지뿐이다.
export async function prepareImage(file: Blob): Promise<ImageBitmap> {
  const bitmap = await createImageBitmap(file);
  const scale = bitmap.width < MIN_WIDTH ? Math.min(3, MIN_WIDTH / bitmap.width) : 1;
  const canvas = new OffscreenCanvas(Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true })!;
  context.imageSmoothingQuality = "high";
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const image = context.getImageData(0, 0, canvas.width, canvas.height);
  const { data } = image;
  let sum = 0;
  for (let i = 0; i < data.length; i += 16) sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
  if (sum / (data.length / 16) / 255 < DARK_LUMA) {
    for (let i = 0; i < data.length; i += 4) {
      data[i] = 255 - data[i];
      data[i + 1] = 255 - data[i + 1];
      data[i + 2] = 255 - data[i + 2];
    }
    context.putImageData(image, 0, 0);
  }
  return canvas.transferToImageBitmap();
}

export async function recognize(file: Blob): Promise<OcrLine[]> {
  const [, bitmap] = await Promise.all([init(), prepareImage(file)]);
  const [result] = (await request("predict", { sources: [{ kind: "imageBitmap", imageBitmap: bitmap }], params: {} }, [bitmap])) as {
    items: { text: string; score: number; poly: [number, number][] }[];
  }[];
  return result.items.map(({ text, score, poly }) => {
    const xs = poly.map(([x]) => x);
    const ys = poly.map(([, y]) => y);
    return { text, score, x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  });
}
