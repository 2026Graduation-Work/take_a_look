// 보유 화면 캡처의 글자 읽기. 사용자 브라우저(웹 워커) 안에서만 돌고 이미지는 어디에도 보내지 않는다.
// 엔진: PaddleOCR.js 0.4.2(Apache-2.0)의 워커 파일 + PP-OCRv5 검출 + 한국어 인식(korean_PP-OCRv5_mobile_rec).
// - 워커 파일(OpenCV, ONNX Runtime이 들어 있는 완성본, 약 11MB)은 jsDelivr에서 버전을 고정해 받는다.
//   패키지를 번들에 넣으면 Turbopack이 워커를 다시 묶다 실패하고, 메인 화면에도 OpenCV 10MB가 실린다.
//   그래서 패키지와 같은 통신 규약(worker-transport-request/response)으로 워커에 직접 말을 건다.
// - 모델(검출 4.8MB + 한국어 인식 13.5MB)은 PaddleX 공식 모델 저장소에서 받는다(CORS 허용, 브라우저가 캐시).
// 모두 '스크린샷으로 불러오기'를 처음 누를 때만 받는다.

export interface OcrLine {
  text: string;
  score: number; // 0~1 인식 확신
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const SDK = "https://cdn.jsdelivr.net/npm/@paddleocr/paddleocr-js@0.4.2/dist/assets/worker-entry-C9UNuyOJ.js";
const ORT_WASM = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.3/dist/"; // 워커 파일에 든 ONNX Runtime과 같은 판
const MODELS = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/";
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
        det: { url: `${MODELS}PP-OCRv5_mobile_det_onnx_infer.tar` },
        rec: { url: `${MODELS}korean_PP-OCRv5_mobile_rec_onnx_infer.tar` },
      },
      runtimeDefaults: DET,
      pipelineBatchSize: 1,
      textDetectionBatchSize: 1,
      textRecognitionBatchSize: 6,
    },
    ortOptions: { backend: "wasm", wasmPaths: ORT_WASM, disableWasmProxy: true },
  },
};

type Response = { kind: string; status: "success" | "error"; requestId: number; payload?: unknown; error?: { message: string } };

let worker: Worker | null = null;
let ready: Promise<unknown> | null = null;
let nextId = 1;
const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();

function request(type: string, payload: unknown, transfer: Transferable[] = []): Promise<unknown> {
  if (!worker) {
    // 같은 출처의 blob 워커에서 고정 판 워커 파일을 불러온다(다른 출처 파일로 바로 워커를 만들 수 없다)
    const boot = URL.createObjectURL(new Blob([`import ${JSON.stringify(SDK)};`], { type: "text/javascript" }));
    worker = new Worker(boot, { type: "module" });
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
    };
  }
  const requestId = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    worker!.postMessage({ kind: "worker-transport-request", type, payload, requestId }, transfer);
  });
}

function init(): Promise<unknown> {
  ready ??= request("init", INIT).catch((error: unknown) => {
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
