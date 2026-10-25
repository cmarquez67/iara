// Conexão WebRTC com a OpenAI Realtime. A oferta SDP passa pelo nosso backend,
// que guarda a chave; o áudio vai direto Chrome <-> OpenAI.
// Tocar a resposta pelo próprio WebRTC é o que permite ao cancelador de eco do Chrome
// removê-la do microfone (conversa simultânea sem hardware caro).

export async function connectRealtime({ micStream, audioEl, onRemoteStream, onEvent, onState }) {
  const pc = new RTCPeerConnection();
  // Clona a trilha: fechar a sessão não pode desligar o microfone da página.
  const micTrack = micStream.getAudioTracks()[0].clone();
  pc.addTrack(micTrack, new MediaStream([micTrack]));

  pc.ontrack = (e) => {
    audioEl.srcObject = e.streams[0];
    audioEl.play().catch(() => {});
    onRemoteStream(e.streams[0]);
  };
  pc.onconnectionstatechange = () => onState(pc.connectionState);

  const dc = pc.createDataChannel('oai-events');
  dc.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* ignora */
    }
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const resp = await fetch('/api/rtc/offer', {
    method: 'POST',
    body: offer.sdp,
    headers: { 'Content-Type': 'application/sdp' },
  });
  if (!resp.ok) {
    micTrack.stop();
    pc.close();
    throw new Error(`Backend recusou a oferta (${resp.status})`);
  }
  await pc.setRemoteDescription({ type: 'answer', sdp: await resp.text() });

  return {
    setMicEnabled(enabled) {
      micTrack.enabled = enabled;
    },
    close() {
      dc.close();
      micTrack.stop();
      pc.getSenders().forEach((s) => s.track?.stop());
      pc.close();
      audioEl.srcObject = null;
      onState('closed');
    },
  };
}
