// Medidor de nível (amplitude real) via Web Audio AnalyserNode.
// Só lê o sinal: não é ligado à saída, então não interfere no áudio nem no cancelamento de eco.

export function createMeter(audioCtx, stream) {
  const source = audioCtx.createMediaStreamSource(stream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  analyser.smoothingTimeConstant = 0.3;
  source.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);

  return {
    level() {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      // fala típica fica entre 0.01 e 0.2 de RMS; escala log para 0..1
      const db = 20 * Math.log10(rms + 1e-6);
      return Math.max(0, Math.min(1, (db + 50) / 40));
    },
    disconnect() {
      source.disconnect();
    },
  };
}
