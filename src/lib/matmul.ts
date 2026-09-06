export async function inspectGpu() {
  if (typeof navigator === "undefined" || !("gpu" in navigator)) {
    return { available: false, label: "", fp16: false, vendor: "" };
  }
  const adapter = await (navigator as Navigator & { gpu?: { requestAdapter: (o?: { powerPreference?: string }) => Promise<{ features?: { has: (n: string) => boolean }; info?: { vendor?: string; description?: string } }> } }).gpu?.requestAdapter({ powerPreference: "high-performance" });
  if (!adapter) return { available: false, label: "", fp16: false, vendor: "" };
  const fp16 = Boolean(adapter.features?.has("shader-f16"));
  const label = adapter.info?.description || adapter.info?.vendor || "WebGPU";
  return { available: true, label, fp16, vendor: adapter.info?.vendor || "" };
}
