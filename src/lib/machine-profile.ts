import { detectSimd } from "./wasm-threads";
import { hasWebGPU } from "./matmul";
import { getSpeechCtor } from "./speech";
import type { Settings } from "./types";

export async function probeMachine() {
  const cores = navigator.hardwareConcurrency || 4;
  const memoryGb = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8;
  const webgpu = await hasWebGPU();
  const simd = detectSimd();
  const speech = Boolean(getSpeechCtor());
  const tier = memoryGb <= 4 || cores <= 4 ? "low" : memoryGb >= 16 && (webgpu || cores >= 8) ? "high" : "mid";
  const settings: Partial<Settings> = {
    engine: speech ? "auto" : "whisper",
    computeDevice: webgpu && tier !== "low" ? "webgpu" : "wasm",
    simdMode: simd.relaxed || simd.fixed ? "auto" : "off",
  };
  return { cores, memoryGb, webgpu, simd, speech, tier, settings };
}
