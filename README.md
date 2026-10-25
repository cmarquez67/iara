# IARA: IA atendente para loja física (MVP)

A IARA vê a loja por uma câmera, cumprimenta quem entra, conversa por voz com o cliente no balcão (pt-BR) e avisa o dono em situações anormais. O mesmo código roda no PC de desenvolvimento (webcam) e na loja (câmera IP por RTSP). A troca é **só pelo `.env`**.

```
Câmera (webcam | RTSP | arquivo) ─► detecção local (movimento → pessoa → zonas) ─► Brain ─► avisos
                                                                                   │
Chrome em quiosque ◄── WebSocket (estado da esfera, comandos) ─────────────────────┤
microfone (cancelamento de eco) ⇄ WebRTC ⇄ OpenAI Realtime ◄── canal de controle ──┘
```

- **Voz:** OpenAI Realtime (`gpt-realtime-2.1-mini`) via WebRTC direto do Chrome. O áudio da IA é tocado pela própria página, então o cancelador de eco do Chrome o remove do microfone e a conversa pode ser simultânea. A chave da API fica só no backend: o Chrome manda a oferta WebRTC ao backend, e o backend chama a OpenAI.
- **Visão:** detecção de pessoas local e barata (YOLOX-nano via ONNX Runtime, só CPU), a 2 quadros por segundo. Imagens só vão para a IA quando há cliente no balcão ou quando o modelo pede (`ver_camera`).
- **Interface:** esfera animada em tela cheia que muda com o estado: ociosa, ouvindo, pensando e falando. Ela reage à amplitude real do áudio.

## Rodar o MVP (Windows)

1. Instale o [uv](https://docs.astral.sh/uv/) (PowerShell):
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
2. Na pasta do projeto:
   ```powershell
   uv sync
   uv run python scripts/download_model.py
   copy .env.example .env          # preencha OPENAI_API_KEY
   copy config.example.yaml config.yaml   # dados da loja e zonas
   uv run python -m iara   # no Windows, "uv run iara" pode ser bloqueado pelo Controle Inteligente de Aplicativos
   ```
3. Em outro terminal, abra a página em modo quiosque:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_kiosk.ps1
   ```
   Na primeira vez, permita o microfone (o perfil dedicado guarda a permissão). Para sair do quiosque: `Alt+F4`.

**Teste rápido na mesa com a webcam:**
1. No `.env`, coloque `CONFIG_FILE=config.webcam.yaml`. Nesse preset, ela cumprimenta quem aparecer por cerca de 1 s e conversa com quem estiver na imagem.
2. Rode `powershell -ExecutionPolicy Bypass -File scripts\dev_windows.ps1`. Ele sobe o backend e abre o Chrome com o painel de debug.

Para testar sem quiosque, abra `http://localhost:8000/?debug=1` no Chrome. O painel de debug mostra:
- botões para simular os estados da esfera;
- **Conversar agora**, que abre a conversa por voz sem depender da câmera;
- a imagem da câmera com zonas e pessoas desenhadas, para calibrar o `config.yaml`;
- o `/healthz` (vídeo, página, sessão de voz, tokens e custo do dia).

> No Linux, o equivalente é `scripts/run_kiosk.sh`. No WSL2, a webcam não aparece por padrão; use `VIDEO_SOURCE=file` ou `none`, ou rode no Windows.

## Trocar para a câmera IP (RTSP)

1. No app Mercusys: **Configurações avançadas → Conta da câmera**, crie usuário e senha RTSP.
2. Descubra o IP da câmera (no app ou no roteador) e, de preferência, fixe-o no roteador (reserva de DHCP).
3. **Teste no VLC antes:** *Mídia → Abrir fluxo de rede* → `rtsp://usuario:senha@IP:554/stream2`. Se abrir no VLC, abre na IARA.
4. No `.env`:
   ```ini
   VIDEO_SOURCE=rtsp
   RTSP_HOST=192.168.0.50
   RTSP_USER=usuario
   RTSP_PASSWORD=senha
   RTSP_PATH=stream2        # baixa resolução, suficiente para detecção
   ```
   Ou só `RTSP_URL=rtsp://usuario:senha@IP:554/stream2`. A Tapo C500 usa o mesmo formato de URL.
5. Recalibre as zonas no `config.yaml` com `?debug=1`. A câmera fica no canto alto direito, então a porta e o balcão aparecem em posições diferentes das da webcam.

A conexão RTSP usa TCP (mais estável em Wi-Fi) e reconecta sozinha se a câmera cair. A senha aparece mascarada nos logs.

**Simular o stream sem a câmera:** `VIDEO_SOURCE=file` e `VIDEO_FILE=algum_video.mp4` (lido em loop, pelo mesmo caminho de código do RTSP). Também dá para usar um RTSP real local com [mediamtx](https://github.com/bluenviron/mediamtx):
```bash
./mediamtx &
ffmpeg -re -stream_loop -1 -i video.mp4 -c copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/stream2
# .env: VIDEO_SOURCE=rtsp  RTSP_URL=rtsp://127.0.0.1:8554/stream2
```

## Variáveis de ambiente (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `OPENAI_API_KEY` | — | Chave da OpenAI (só no backend) |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1-mini` | Modelo de voz |
| `OPENAI_VOICE` | `marin` | Voz da IA |
| `OPENAI_SAFETY_ID` | `iara-loja` | Identificador da loja (não da pessoa) para a OpenAI |
| `VIDEO_SOURCE` | `webcam` | `webcam`, `rtsp`, `file` ou `none` |
| `WEBCAM_INDEX` | `0` | Índice da webcam |
| `WEBCAM_BACKEND` | `any` | `any`, `dshow`, `msmf` ou `v4l2` (no Windows, `dshow` costuma abrir mais rápido) |
| `RTSP_URL` | — | URL completa; se preenchida, ignora os campos abaixo |
| `RTSP_HOST` / `RTSP_PORT` / `RTSP_USER` / `RTSP_PASSWORD` / `RTSP_PATH` | — / `554` / — / — / `stream2` | Partes da URL RTSP |
| `VIDEO_FILE` | — | Arquivo de vídeo para `VIDEO_SOURCE=file` |
| `DETECTION_FPS` | `2` | Quadros por segundo analisados |
| `DETECTOR_MODEL` | `models/yolox_nano.onnx` | Modelo de detecção |
| `AUDIO_DUPLEX` | `full` | `full` (simultâneo) ou `half` (walkie-talkie: muta o microfone enquanto a IA fala) |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Servidor local |
| `CONFIG_FILE` | `config.yaml` | Dados da loja, zonas, tempos e textos |
| `LOG_LEVEL` | `INFO` | Nível de log |

## `config.yaml`

- **`store`:** nome, horário, endereço, produtos e preços, outras informações. É o que a IA sabe responder; ela não inventa o que não está aqui.
- **`zones`:** polígonos `door`, `counter` e `staff` em coordenadas de 0 a 1 (x da esquerda para a direita, y de cima para baixo). Vale o ponto dos pés de cada pessoa.
- **`detection`:** limiares, tempo para "pessoa parada" (`lingering_s`) e para "cliente sem atendimento" (`unattended_s`).
- **`brain`:**
  - `greet_cooldown_s`: intervalo mínimo entre saudações;
  - `alert_cooldown_s`: intervalo mínimo entre avisos do mesmo tipo;
  - `session_idle_close_s`: fecha a sessão de voz com a loja vazia.
- **`texts.greeting`:** `{periodo}` vira "Bom dia", "Boa tarde" ou "Boa noite"; `{loja}` vira o nome da loja.

## Como a IARA decide

| Situação | Ação |
|---|---|
| Pessoa entra pela zona da porta | Abre a sessão de voz e cumprimenta (com cooldown); quem só passa na frente da porta não é cumprimentado |
| Cliente na zona do balcão fala | Manda uma imagem da cena (só no primeiro turno) e responde |
| Alguém fala fora do balcão | Ignora (não responde a conversas paralelas) |
| A IA precisa olhar algo | Ferramenta `ver_camera`: manda uma imagem nova |
| Cliente pede uma pessoa ou a IA não sabe | Ferramenta `chamar_atendente` → aviso |
| Cliente no balcão há mais de `unattended_s` sem ninguém na zona do atendente | Aviso `cliente_esperando` |
| Pessoa parada há mais de `lingering_s` fora do balcão | Aviso `pessoa_parada` |
| Loja vazia por `session_idle_close_s` | Fecha a sessão de voz (para de gastar) |

No MVP, os avisos aparecem no console como `[AVISO ...]`.

## Testes

```bash
uv run pytest                 # sem hardware: Brain, eventos, tracker, zonas, mapeamento Realtime, vídeo de arquivo, servidor
uv run pytest -m integration  # RTSP real: precisa do mediamtx em localhost:8554 e ffmpeg
uv run ruff check
```

## Desenvolvimento (WSL + Windows)

O código mora numa pasta só, `C:\Users\Caiom\code\iara`. No WSL, `~/code/iara` é um atalho para `/mnt/c/Users/Caiom/code/iara`, então editar de um lado é editar do outro.

Cada sistema tem o próprio ambiente Python; os dois não podem dividir o mesmo `.venv`.
- **Windows:** usa o `.venv` padrão. Rode com `scripts\dev_windows.ps1` ou `uv run python -m iara`, sem `UV_PROJECT_ENVIRONMENT` definido.
- **WSL** (testes, edição, git): usa um ambiente fora da pasta do projeto. Antes de usar `uv`, rode:
  ```bash
  export UV_PROJECT_ENVIRONMENT=~/.venvs/iara UV_LINK_MODE=copy
  ```
  O Claude Code já recebe essas variáveis por `.claude/settings.local.json`.

O git roda pelo WSL. O `.gitattributes` fixa o fim de linha em LF, e `core.fileMode=false` evita que o `/mnt/c` marque arquivos como modificados por causa de permissões.

## Privacidade (LGPD)

- Nada é gravado: nem áudio, nem vídeo, nem as imagens enviadas à IA (ficam só em memória).
- Transcrições não são pedidas nem registradas. Os logs têm só tipos de evento e contagens de tokens.
- A imagem de calibração (`/api/debug/frame.jpg`) é gerada na hora e o servidor escuta só em `127.0.0.1`.
- A IA é instruída a não descrever nem tentar identificar pessoas.
- Lembre-se do aviso de monitoramento na loja.

## Custos

Cada resposta registra no log os tokens (texto, áudio, imagem, cache) e o custo estimado do dia, com preços configuráveis em `prices` no `config.yaml`. Os valores vêm da tabela da OpenAI de outubro de 2026; confira se mudaram. A sessão de voz só fica aberta com gente na loja.

## Problemas comuns

- **A IA se ouve (eco):** confirme que o som sai pelo Chrome da página da IARA. Se o eco persistir com as caixas altas, use `AUDIO_DUPLEX=half`.
- **"Toque para ativar o som":** o Chrome bloqueou o áudio automático. O `run_kiosk` usa `--autoplay-policy=no-user-gesture-required`.
- **"Microfone indisponível":** permita o microfone para `localhost` nas configurações do Chrome (perfil do quiosque).
- **Webcam não abre no Windows:** teste `WEBCAM_BACKEND=dshow` ou outro `WEBCAM_INDEX`.

## Estrutura

```
src/iara/
  app.py              composição: único lugar que escolhe implementações pela configuração
  config.py           .env + config.yaml
  domain.py           Frame, BBox, Track, eventos de cena
  video/              VideoSource + OpenCvSource (webcam/RTSP/arquivo, reconexão)
  vision/             movimento, detector YOLOX, tracker, zonas, EventDetector, pipeline
  voice/              VoiceSession (interface neutra) + OpenAI Realtime + fake para testes
  brain/              regras, prompts em pt-BR, ferramentas
  notify/             Notifier (console; depois WhatsApp/Telegram)
  web/                FastAPI (página, WebSocket, oferta WebRTC, debug) + página estática
    static/orb.js     a esfera: componente isolado (setState/setLevel), troque o visual aqui
```
