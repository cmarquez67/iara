// WebSocket com o backend, com reconexão automática (espera crescente até 10 s).

export function createSocket(url, { onMessage, onStatus }) {
  let ws = null;
  let delay = 500;
  let closedByUser = false;

  function connect() {
    ws = new WebSocket(url);
    ws.onopen = () => {
      delay = 500;
      onStatus(true);
    };
    ws.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data));
      } catch (err) {
        console.error('Mensagem inválida do backend', err);
      }
    };
    ws.onclose = () => {
      onStatus(false);
      if (closedByUser) return;
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 10000);
    };
    ws.onerror = () => ws.close();
  }

  connect();

  return {
    send(message) {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
    },
    close() {
      closedByUser = true;
      ws?.close();
    },
  };
}
