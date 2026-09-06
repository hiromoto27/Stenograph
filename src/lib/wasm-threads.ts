export type SimdMode = "auto" | "off" | "fixed" | "relaxed";

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
