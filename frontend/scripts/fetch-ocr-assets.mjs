// 글자 읽기 도구(워커, ONNX Runtime wasm, 모델)를 빌드 때 받아 public/ocr/에 둔다(git에는 넣지 않는다, 약 55MB).
// 같은 출처에서 주면 화면 CSP에 외부 출처와 'unsafe-eval'을 열 필요가 없고(워커는 /ocr/ 응답 헤더의 CSP를 따로 받는다),
// 판을 sha256으로 고정해 CDN 쪽 파일이 바뀌어도 그대로 쓰지 않는다. 판을 올리면 주소와 해시를 같이 바꾼다.
// 이 레포 Release(ocr-assets-v1)의 사본을 먼저 받고, 실패할 때만 원 출처(jsDelivr, Baidu 모델 저장소)를 쓴다.
// prebuild에서는 받기 실패면 멈추고, predev(--soft)에서는 경고 한 줄 뒤 넘어간다. 이미 받은 파일은 해시만 확인한다.
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { setDefaultAutoSelectFamilyAttemptTimeout } from "node:net";

// 모델 저장소(중국)는 첫 연결이 느려 Node 기본값(250ms 안에 IPv4가 안 붙으면 IPv6로 넘김)으로는 끊긴다
setDefaultAutoSelectFamilyAttemptTimeout(10_000);

// 판(v1)을 경로에 넣어 1년 immutable 캐시를 건다(next.config.ts). 파일이나 해시를 바꾸면 v2로 옮기고 recognize.ts도 같이
const DIR = new URL("../public/ocr/v1/", import.meta.url);
const MIRROR = "https://github.com/2026Graduation-Work/take_a_look/releases/download/ocr-assets-v1/";
const NPM = "https://cdn.jsdelivr.net/npm/";
const MODELS = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/";
const ASSETS = [
  // PaddleOCR.js 0.4.2(Apache-2.0) 워커 완성본(OpenCV, ONNX Runtime 포함)
  [`${NPM}@paddleocr/paddleocr-js@0.4.2/dist/assets/worker-entry-C9UNuyOJ.js`, "477db3f009c118823a5f9ebe15f1e96c1c464165715ba28a9884290f61addf52"],
  // onnxruntime-web 1.24.3(MIT): 워커 안 ONNX Runtime과 같은 판
  [`${NPM}onnxruntime-web@1.24.3/dist/ort-wasm-simd-threaded.jsep.mjs`, "9a99acd12acc495184c9ea4d458ac9424f8180aacfbc7b8371ed64f9351e4a81"],
  [`${NPM}onnxruntime-web@1.24.3/dist/ort-wasm-simd-threaded.jsep.wasm`, "2e0a3d0e3f6b7c13ecfaba38c13691fd19c9ed470e72f9d7d8416ca59ab6dbcd"],
  // PaddleX 공식 모델(Apache-2.0): PP-OCRv5 검출, 한국어 인식
  [`${MODELS}PP-OCRv5_mobile_det_onnx_infer.tar`, "781056046c9ed77a15c94681605db6a0f62317c2e9cce6931c71da2478d4bc30"],
  [`${MODELS}korean_PP-OCRv5_mobile_rec_onnx_infer.tar`, "568ed8b43a260adc9f484d92105e425ea8cddf8ce16940c177bc12864cfb0eb0"],
];

const sha256 = (data) => createHash("sha256").update(data).digest("hex");

// 한 주소에서 받아 해시까지 맞으면 내용을, 아니면 오류를 던진다(연결 오류는 3번까지 다시)
async function download(url, hash) {
  let response;
  for (let attempt = 1; ; attempt++) {
    try {
      response = await fetch(url);
      break;
    } catch (error) {
      if (attempt === 3) throw error;
    }
  }
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  const data = Buffer.from(await response.arrayBuffer());
  if (sha256(data) !== hash) throw new Error(`해시가 다름: ${url}`);
  return data;
}

async function fetchAll() {
  await mkdir(DIR, { recursive: true });
  for (const [origin, hash] of ASSETS) {
    const name = origin.split("/").pop();
    const file = new URL(name, DIR);
    const existing = await readFile(file).catch(() => null);
    if (existing && sha256(existing) === hash) continue;
    let data;
    let source = "release";
    try {
      data = await download(MIRROR + name, hash);
    } catch (error) {
      console.warn(`ocr: Release 사본 받기 실패, 원 출처로 받는다 (${error.message})`);
      data = await download(origin, hash);
      source = "origin";
    }
    await writeFile(file, data);
    console.log(`ocr: ${name} ${(data.length / 1e6).toFixed(1)}MB (${source})`);
  }
}

try {
  await fetchAll();
} catch (error) {
  if (!process.argv.includes("--soft")) throw new Error(`글자 읽기 도구 받기 실패 ${error.message}`);
  console.warn(`ocr: 글자 읽기 도구를 받지 못해 캡처 불러오기만 동작하지 않는다, 나머지 개발은 그대로 (${error.message})`);
}
