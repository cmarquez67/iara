// Orquestra a página: microfone, WebRTC, esfera e canal com o backend.
// O backend decide o estado; a página só desenha e transporta o áudio.

import { createOrb } from './orb.js';
import { createSocket } from './ws.js';
import { connectRealtime } from './rtc.js';
import { createMeter } from './audio.js';

const CAPTIONS = {
  idle: '',
  listening: 'Pode falar, estou ouvindo',
  thinking: 'Só um instante',
  speaking: '',
};

const debug = new URLSearchParams(location.search).has('debug');
const orb = createOrb(document.getElementById('orb'));
const captionEl = document.getElementById('caption');
const offlineEl = document.getElementById('offline');
const unlockEl = document.getElementById('unlock');
const audioEl = document.getElementById('voice');

let state = 'idle';
let duplex = 'full';
let micStream = null;
let micMeter = null;
let voiceMeter = null;
let session = null;
let connecting = false;
const audioCtx = new AudioContext();

function setState(next) {
  state = next;
  orb.setState(next);
  captionEl.textContent = CAPTIONS[next] ?? '';
  captionEl.dataset.visible = captionEl.textContent ? 'true' : 'false';
}

function showProblem(text) {
  captionEl.textContent = text;
  captionEl.dataset.visible = 'true';
}

// --- Microfone (capturado uma vez, reaproveitado entre sessões) ---
async function initMic() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    micMeter = createMeter(audioCtx, micStream);
  } catch (err) {
    console.error(err);
    showProblem('Microfone indisponível. Permita o acesso ao microfone no Chrome e recarregue a página.');
  }
}

// O Chrome só libera áudio depois de um toque, a menos que rode com
// --autoplay-policy=no-user-gesture-required (ver scripts/run_kiosk).
function checkAudioUnlocked() {
  if (audioCtx.state === 'running') {
    unlockEl.hidden = true;
    return;
  }
  unlockEl.hidden = false;
}
unlockEl.addEventListener('click', async () => {
  await audioCtx.resume();
  audioEl.play().catch(() => {});
  checkAudioUnlocked();
});
audioCtx.onstatechange = checkAudioUnlocked;

// --- Sessão de voz ---
async function openVoice() {
  if (session || connecting || !micStream) {
    if (!micStream) socket.send({ type: 'rtc.state', state: 'failed' });
    return;
  }
  connecting = true;
  try {
    session = await connectRealtime({
      micStream,
      audioEl,
      onRemoteStream: (stream) => {
        voiceMeter?.disconnect();
        voiceMeter = createMeter(audioCtx, stream);
      },
      onEvent: (event) => {
        if (!event.type?.startsWith('output_audio_buffer.')) return;
        if (duplex === 'half') session?.setMicEnabled(event.type !== 'output_audio_buffer.started');
        socket.send(event);
      },
      onState: (s) => socket.send({ type: 'rtc.state', state: s }),
    });
  } catch (err) {
    console.error(err);
    socket.send({ type: 'rtc.state', state: 'failed' });
  } finally {
    connecting = false;
  }
}

function closeVoice() {
  const s = session;
  session = null;
  voiceMeter?.disconnect();
  voiceMeter = null;
  s?.close();
}

// --- Backend ---
const socket = createSocket(`ws://${location.host}/ws`, {
  onStatus: (online) => {
    offlineEl.hidden = online;
    if (!online) {
      closeVoice();
      setState('idle');
    }
  },
  onMessage: (msg) => {
    switch (msg.type) {
      case 'config':
        duplex = msg.duplex || 'full';
        break;
      case 'state':
        setState(msg.state);
        break;
      case 'voice.connect':
        openVoice();
        break;
      case 'voice.disconnect':
        closeVoice();
        break;
    }
  },
});

// --- Nível de áudio para a esfera ---
function tick() {
  let level = 0;
  if (state === 'speaking') level = voiceMeter?.level() ?? 0;
  else if (state === 'listening') level = micMeter?.level() ?? 0;
  orb.setLevel(level);
  requestAnimationFrame(tick);
}

// --- Modo debug (?debug=1): simula estados, conversa sem vídeo, mostra zonas ---
function initDebug() {
  const panel = document.getElementById('debug');
  panel.hidden = false;
  for (const s of ['idle', 'listening', 'thinking', 'speaking']) {
    const b = document.createElement('button');
    b.textContent = s;
    b.onclick = () => setState(s);
    panel.querySelector('.states').append(b);
  }
  let talking = false;
  const talk = panel.querySelector('.talk');
  talk.onclick = async () => {
    talking = !talking;
    talk.textContent = talking ? 'Parar conversa' : 'Conversar agora';
    await fetch('/api/debug/talk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on: talking }),
    });
  };
  // Vídeo ao vivo (MJPEG); se o backend reiniciar, reconecta.
  const img = panel.querySelector('img');
  const connectVideo = () => {
    img.hidden = false;
    img.src = `/api/debug/stream.mjpg?t=${Date.now()}`;
  };
  img.onerror = () => {
    img.hidden = true;
    setTimeout(connectVideo, 2000);
  };
  connectVideo();
  const health = panel.querySelector('pre');
  setInterval(async () => {
    try {
      health.textContent = JSON.stringify(await (await fetch('/healthz')).json(), null, 1);
    } catch {
      health.textContent = 'backend offline';
    }
  }, 1000);
}

setState('idle');
checkAudioUnlocked();
initMic();
if (debug) initDebug();
requestAnimationFrame(tick);
