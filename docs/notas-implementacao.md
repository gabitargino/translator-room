# Notas de implementação

Diário de bordo da Atividade 04. Aqui entram medições brutas, decisões, problemas e
pendências. O que for relevante é resumido depois no
[relatório](relatorio-atividade04.md).

Formato: entradas por data, mais recentes no final.

---

## 2026-11-20

### Análise do projeto original (open-realtime-translate, `3bbf77c`)

- Pontos reaproveitáveis identificados: `TranslationSession` (VAD → ASR → MT → TTS
  por conexão), endpoint WebRTC (`ort/webrtc.py`), backends `mock`.
- Bloqueios:
  - Uma sessão = uma entrada e **um** idioma de saída. Seria preciso separar quem
    fala (ASR) de quem ouve (MT + TTS).
  - `ort/inference.py`: um único executor com 1 thread para toda a inferência
    (exigência do MLX). Duas direções simultâneas seriam processadas em série.
  - Perfil CUDA padrão (Qwen3-ASR 1.7B + TranslateGemma 4B bf16 + Qwen3-TTS 1.7B)
    não cabe em 6 GB de VRAM. O backend `translategemma_torch` não quantiza.
  - O TTS padrão em CPU (Supertonic) não tem chinês. Só o Kokoro cobre PT-BR e ZH.
- Risco identificado e ainda válido para qualquer base: **conversa cruzada**. Com
  as pessoas frente a frente, o microfone de A capta a voz de B. Mitigação
  planejada: idioma de fala declarado por participante, descartar trechos em que
  o idioma detectado é diferente, `echoCancellation`/`noiseSuppression` no
  `getUserMedia`.

### Decisão: trocar o projeto base para o PolyTalk CE (`2aeadfd`)

- Motivos e comparação no relatório (seção 2).
- Alternativa descartada: live-translate (Web Speech API no navegador). Mais
  simples, mas depende de internet e do Google, o que quebra o requisito de rede local.
- Achado: o PolyTalk tem modo `conversation` (`app/services/pipeline_service.py`,
  `_conversation_direction` e `_process_conversation_streaming`), que é uma conversa
  bidirecional em um único dispositivo. Serve de base para as salas.
- O WebSocket `/ws/translate` recebe `source_language`, `target_language`, `mode` e
  `custom_instruction`. O provedor de tradução é configurado só no servidor
  (`config/config.yaml`).
- O Docker Compose do PolyTalk **não** inclui serviço de tradução (stt, tts,
  supertonic-tts, polytalk). A tradução é sempre externa, via `TRANSLATION_BASE_URL`.
- Configuração padrão do STT voltada a frases longas: `STT_STREAM_CHUNK_SECONDS=3.0`,
  `STT_PAUSE_FLUSH_SECONDS=1.2`, `STT_EMIT_INTERVAL_SECONDS=4.5`. O guia de produção
  sugere `1.2` para o chunk. **Pendente:** ajustar e medir.
- Roteamento de vozes em `config.yaml.example`: `zh` usa Piper `zh_CN-huayan-medium`;
  `pt` usa Supertonic.

### Ambiente

- Windows 11, RTX 4050 Laptop 6 GB, Ryzen 7 8745HS, 15,3 GB RAM, 111 GB livres.
- Docker 29.5.3 + WSL2 (Ubuntu) já instalados.
- RAM livre no momento da checagem: 1,7 GB. **Atenção:** fechar programas ao rodar
  a pilha completa; considerar limitar o WSL via `.wslconfig`.
- Ollama 0.40.16 instalado via `winget install Ollama.Ollama`, rodando fora do
  Docker para usar a GPU sem configuração extra.

### Teste de viabilidade: tradução local via Ollama

Script: chamada a `/v1/chat/completions` com o prompt de sistema do PolyTalk,
temperatura 0, 6 frases por direção. Primeiro carregamento descartado.

**Problema encontrado:** a primeira rodada deu ~2,3–2,5 s por frase, com tempo
quase constante para frases curtas e longas. A causa era o `localhost` no Windows,
que tenta IPv6 (`::1`) primeiro e só cai para IPv4 depois de ~2 s. Trocando para
`127.0.0.1` o tempo caiu ~10×.
→ **Ao configurar o PolyTalk, usar `127.0.0.1` ou `host.docker.internal`, nunca `localhost`.**

Resultados com `127.0.0.1` (modelo já carregado na GPU):

| Modelo | VRAM (`ollama ps`) | Carga (fria / em cache) | PT→ZH mediana / máx | ZH→PT mediana / máx |
|---|---|---|---|---|
| translategemma:4b | 2,9 GB | 70 s / 7,3 s | 0,28 / 0,31 s | 0,35 / 0,40 s |
| qwen2.5:3b | 2,2 GB | 39 s / 0,4 s | 0,16 / 0,20 s | 0,25 / 0,29 s |

Traduções obtidas:

| Origem | translategemma:4b | qwen2.5:3b |
|---|---|---|
| Oi, tudo bem? Prazer em te conhecer. | 你好，很高兴认识你。 | 你好，你好吗？很高兴认识你。 |
| Você sabe onde fica a estação de metrô mais próxima? | 最近的地铁站在哪里？ | 你知道最近的地铁站在哪里吗？ |
| Eu trabalho com desenvolvimento de software há cinco anos. | 我从事软件开发工作已经五年了。 | 我从事软件开发工作已有五年。 |
| Quanto custa esse produto se eu comprar duas unidades? | 如果我购买两件，这件产品的价格是多少？ | 购买两单位这个产品要多少钱？ (truncado/estranho) |
| Desculpa, pode falar um pouco mais devagar? | 您能请您再说一遍吗？ (**erro: "repetir"**) | 对不起，可以再慢一点吗？ |
| Amanhã vamos nos reunir às três da tarde para fechar o contrato. | 明天下午三点我们将见面，以签署合同。 | 我们明天下午三点开会来签署合同。 |
| 你好，很高兴认识你。 | Olá, é um prazer conhecê-lo. | Olá, é um prazer conhecer você. |
| 请问洗手间在哪里？ | Onde fica o banheiro? | Onde está o banheiro? |
| 我们公司明年打算在巴西开一家分店。 | Nossa empresa planeja abrir uma filial no Brasil no próximo ano. | (idem) |
| 这个价格有点贵，能便宜一点吗？ | O preço está um pouco alto, seria possível oferecer um desconto? | Este preço está um pouco caro, tem como ficar mais em conta? |
| 不好意思，我没听清楚，你可以再说一遍吗？ | Desculpe, não entendi. Você poderia repetir, por favor? | Desculpe, eu não ouvi bem, você poderia repetir, **please**? |
| 你第一次来中国吗？觉得这里的菜怎么样？ | É a sua primeira vez na China? O que achou da comida daqui? | Você foi à China pela primeira vez? Como foi a comida aqui? (**sentido alterado**) |

Leitura: o `translategemma:4b` tem melhor qualidade geral, sobretudo em ZH→PT; o
`qwen2.5:3b` é mais rápido, mas mistura idiomas. Os dois cabem com folga no
orçamento de latência. **Candidato inicial: `translategemma:4b`.**

**Pendente:** verificar se o `translategemma` responde bem ao formato de prompt
do PolyTalk em frases fragmentadas (saída do STT incremental).

### Decisão: modelo de tradução = `translategemma:4b`

Confirmado pela equipe. O `qwen2.5:3b` continua baixado no Ollama só para
comparação; pode ser removido com `ollama rm qwen2.5:3b` (libera 1,9 GB).

### Achados sobre o PolyTalk usados no planejamento

- Navegador: `getUserMedia` já com `echoCancellation` e `noiseSuppression`; áudio
  convertido para 16 kHz e enviado em pedaços binários pelo WebSocket
  (`app/static/js/audio-recorder.js`).
- Para cada conexão, o app abre uma conexão própria com o serviço STT
  (`app/services/whisper_service.py`).
- O modo `conversation` usa `emit_policy="pause"` e
  `candidate_languages=[origem, destino]`, e o contexto de tradução fica desligado.
- A voz é devolvida como **link para um arquivo** (`audio_url`), tocado no navegador
  com `new Audio(url)`. Os arquivos ficam em `/media/output`.
- O servidor não tem HTTPS; `ALLOWED_ORIGINS` aceita só `localhost:9000` por padrão.
- A interface tem 14 idiomas, mas **não tem chinês**.
- STT com `STT_MODEL_WORKERS=2` → duas falas simultâneas podem ser processadas.

### Planejamento

Plano completo em [planejamento.md](planejamento.md): 8 etapas, subtarefas com
critério de pronto, árvore de prioridade, riscos e questões em aberto.

---

## 2026-11-21 – Etapa 0 (branch `etapa-0-preparacao`)

### 0.1 Importação do PolyTalk com histórico

- `git remote add upstream https://github.com/PolyTalkIO/polytalk.git`, com a URL de
  push trocada para `DISABLED_no_push_to_upstream` (garante a regra da disciplina:
  um `git push upstream` acidental falha).
- `git merge --allow-unrelated-histories 2aeadfd` (v0.4.0-ce). Único conflito: o
  `README.md`. Resolvido mantendo o README original do PolyTalk com um bloco no topo
  explicando o fork.
- A pasta `docs/` do PolyTalk (`benchmarking.md`, `production-deployment.md`,
  `provider-extension.md`) conviveu sem conflito com a nossa documentação.

### 0.2 Fluxo de branches

- Regra resumida no bloco do fork no `README.md`; branch `etapa-0-preparacao` já
  existia (criada junto com o planejamento, commit `365d5bf`).
