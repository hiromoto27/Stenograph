export type SimdMode = "auto" | "off" | "fixed" | "relaxed";

export type WasmTune = {
  cores: number;
  memoryGb: number;
  threads: number;
  proxy: boolean;
  simd: boolean | "fixed" | "relaxed";
  simdSupported: boolean;
  simdMode: SimdMode;
};

export function simdSupported() {
  if (typeof WebAssembly === "undefined") return false;
  try {
    const bytes = Uint8Array.from([
      0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x01, 0x60, 0x00, 0x01, 0x7b,
      0x03, 0x02, 0x01, 0x00, 0x0a, 0x0a, 0x01, 0x08, 0x00, 0x41, 0x00, 0xfd, 0x0f, 0xfd, 0x62, 0x0b,
    ]);
    return WebAssembly.validate(bytes);
  } catch {
    return false;
  }
}

export function resolveSimd(mode: SimdMode): boolean | "fixed" | "relaxed" {
  if (mode === "off" || !simdSupported()) return false;
  if (mode === "relaxed") return "relaxed";
  return "fixed";
}

export function tuneWasm(mode: SimdMode = "auto"): WasmTune {
  const cores = typeof navigator !== "undefined" ? Math.max(1, navigator.hardwareConcurrency || 4) : 4;
  const memoryGb =
    typeof navigator !== "undefined"
      ? (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8
      : 8;
  let threads = 1;
  if (memoryGb >= 8 && cores >= 6) threads = 2;
  if (memoryGb >= 16 && cores >= 12) threads = 3;
  if (cores <= 4 || memoryGb <= 4) threads = 1;
  return {
    cores,
    memoryGb,
    threads: Math.min(threads, 3),
    proxy: true,
    simd: resolveSimd(mode),
    simdSupported: simdSupported(),
    simdMode: mode,
  };
}

export function applyWasmTune(
  wasm: { numThreads?: number; proxy?: boolean; simd?: boolean | string },
  mode: SimdMode = "auto",
) {
  const t = tuneWasm(mode);
  wasm.numThreads = t.threads;
  wasm.proxy = t.proxy;
  wasm.simd = t.simd;
  return t;
}
