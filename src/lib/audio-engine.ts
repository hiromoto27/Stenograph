export type Device = { deviceId: string; label: string; kind: MediaDeviceKind };
export async function listAudioDevices(): Promise<Device[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter((d) => d.kind === "audioinput").map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Микрофон ${i + 1}`, kind: d.kind }));
}
export async function openMic(deviceId?: string) {
  return navigator.mediaDevices.getUserMedia({ audio: deviceId ? { deviceId: { exact: deviceId }, echoCancellation: true, noiseSuppression: true } : { echoCancellation: true, noiseSuppression: true }, video: false });
}
