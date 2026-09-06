export type Device = { deviceId: string; label: string; kind: MediaDeviceKind };

export async function listAudioDevices(): Promise<Device[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter((d) => d.kind === "audioinput").map((d, i) => ({
    deviceId: d.deviceId,
    label: d.label || `Микрофон ${i + 1}`,
    kind: d.kind,
  }));
}

export async function openMic(deviceId?: string) {
  return navigator.mediaDevices.getUserMedia({
    audio: deviceId
      ? { deviceId: { exact: deviceId }, echoCancellation: true, noiseSuppression: true }
      : { echoCancellation: true, noiseSuppression: true },
    video: false,
  });
}

export function attachAnalyser(stream: MediaStream) {
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  const time = new Uint8Array(analyser.fftSize);
  const freq = new Uint8Array(analyser.frequencyBinCount);
  return {
    ctx,
    analyser,
    sample() {
      analyser.getByteTimeDomainData(time);
      analyser.getByteFrequencyData(freq);
      let sum = 0;
      for (let i = 0; i < time.length; i++) {
        const v = (time[i] - 128) / 128;
        sum += v * v;
      }
      return { time, freq, rms: Math.sqrt(sum / time.length) };
    },
    async close() {
      src.disconnect();
      await ctx.close().catch(() => undefined);
    },
  };
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}
