export type ComputeDevice = "auto" | "webgpu" | "wasm";

export async function hasWebGPU() {
  if (typeof navigator === "undefined" || !("gpu" in navigator)) return false;
  try {
    return Boolean(await (navigator as Navigator & { gpu?: { requestAdapter: () => Promise<unknown> } }).gpu?.requestAdapter());
  } catch {
    return false;
  }
}

export async function planMatmul(want: ComputeDevice = "auto") {
  const webgpu = await hasWebGPU();
  if (want === "wasm" || !webgpu) return { want, device: "wasm" as const, dtype: "q8" as const, webgpu };
  return { want, device: "webgpu" as const, dtype: "fp16" as const, webgpu };
}
