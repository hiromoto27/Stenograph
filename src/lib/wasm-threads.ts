export type WasmTune = {
  cores: number;
  memoryGb: number;
  threads: number;
  proxy: boolean;
  simd: boolean;
};

export function tuneWasm(): WasmTune {
  const cores = typeof navigator !== "undefined" ? Math.max(1, navigator.hardwareConcurrency || 4) : 4;
  const memoryGb =
    typeof navigator !== "undefined"
      ? (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8
      : 8;
  let threads = 1;
  if (memoryGb >= 8 && cores >= 6) threads = 2;
  if (memoryGb >= 16 && cores >= 12) threads = 3;
  if (cores <= 4 || memoryGb <= 4) threads = 1;
  threads = Math.min(threads, 3);
  return { cores, memoryGb, threads, proxy: true, simd: true };
}

export function applyWasmTune(wasm: { numThreads?: number; proxy?: boolean; simd?: boolean | string }) {
  const t = tuneWasm();
  wasm.numThreads = t.threads;
  wasm.proxy = t.proxy;
  if (typeof wasm.simd === "boolean" || wasm.simd === undefined) wasm.simd = t.simd;
  return t;
}
