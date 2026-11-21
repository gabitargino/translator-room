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
- A interface tem 13 idiomas próprios (menus, botões), mas **não tem chinês**. Os seletores de idioma de tradução têm `zh` (corrigido em 2026-11-21).
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

### 0.3 Configuração local (`.env` e `config.yaml`)

- `.env` e `config/config.yaml` **já estavam** no `.gitignore` do PolyTalk; nada a
  acrescentar. Confirmado com `git check-ignore -v`.
- `.env.example`: seção de tradução aponta para o Ollama
  (`http://host.docker.internal:11434`, `translategemma:4b`, chave vazia) nos dois
  provedores (`TRANSLATION_*` e `TRANSLATEGAMMA_*`), com o aviso sobre `localhost`.
- Chave vazia funciona: `_bearer_headers` em `app/services/translation_service.py`
  só envia `Authorization` quando há chave.
- `config/config.yaml.example`: só um comentário explicando os `mock_mode`.
- Locais criados por cópia dos exemplos (mock ligado por padrão, para a 0.4).

### 0.4 Modo mock

- Execução local, fora do Docker: `python -m venv .venv`, `pip install -r
  requirements.txt -r test-requirements.txt`, `python -m app.main`. Python 3.13.12
  funcionou sem ajustes (o PolyTalk pede 3.10+).
- `GET /api/health` → `{"status":"healthy","version":"0.4.0"}`; `GET /` e os 11
  recursos estáticos referenciados pela página (CSS, JS, logo) → 200.
- Teste de fumaça por script (fora do repositório): WebSocket
  `/api/ws/translate?source_language=pt&target_language=zh&mode=conversation`, 4 s de
  áudio sintético. Recebidos `transcription` → `conversation_turn` (`[zh] Hello` etc.)
  → `tts` com `audio_url` (WAV servido em `/media/output/…`) → `complete`.
- Comportamento do mock: o transcritor falso segue um roteiro fixo em inglês e
  **fecha a conexão sozinho** ao terminar (`complete`). Clientes de teste precisam
  tolerar isso.
- **Pendente:** conferência visual da interface no navegador. A extensão do Chrome
  usada pelo agente não estava conectada; fica para um integrante abrir
  `http://127.0.0.1:9000` e clicar em iniciar.

### 0.8 Linha de base dos testes originais

Feita antes da 0.5 porque não depende do Docker (o daemon estava parado).
Comando do CI original: `pytest tests/ -v` (o CI usa Python 3.12 no Ubuntu; aqui,
Python 3.13.12 no Windows, dentro do `.venv`).

| Execução | Passou | Falhou | Cobertura (`app/`) | Tempo |
|---|---|---|---|---|
| Direta, com o `.env` local presente | 452 | 6 | 75,79 % | 138 s |
| Sem o `.env` local e com `PYTHONUTF8=1` | **454** | **4** | **75,90 %** | 100 s |

As 6 falhas são do ambiente, não do código:

| Teste | Causa |
|---|---|
| `test_app.py::TestSTTCadence::test_stt_pause_flush_seconds_default` | O app carrega o `.env` com `python-dotenv`; o `.env.example` traz `STT_PAUSE_FLUSH_SECONDS=1.2` e o teste espera o padrão do código, `1.0`. Passa sem o `.env` local |
| `test_i18n.py::test_locale_catalogs_have_required_shape` | Lê os catálogos sem `encoding=` e o Windows usa cp1252. Passa com `PYTHONUTF8=1` |
| `test_app.py::TestBenchmarks::test_stt_benchmark_missing_audio_has_clear_error` e `test_pipeline_benchmark_missing_audio_has_clear_error` | Comparam a mensagem com `/tmp/...` literal; no Windows o `Path` vira `\tmp\...`. Só no Windows |
| `test_logger_detailed.py::TestSetupFileLogger::test_setup_file_logger_with_dir` e `test_setup_file_logger_creates_dir` | O `TemporaryDirectory` tenta apagar o `polytalk.log` ainda aberto pelo handler de log (WinError 32). Só no Windows |

**Linha de base adotada:** 454/458 no Windows com `PYTHONUTF8=1` e sem `.env`, e as
4 restantes conhecidas como específicas do Windows. Os testes originais **não** foram
alterados. Daqui em diante, qualquer falha além dessas 4 é regressão nossa.
Comando de referência (Git Bash):

```bash
mv .env .env.off; PYTHONUTF8=1 .venv/Scripts/python -m pytest tests/ -q; mv .env.off .env
```

Observação: o `.github/workflows/ci.yml` do PolyTalk também roda no nosso fork a
cada push (job `pre-commit` + `tests` no Ubuntu). Isso serve de conferência no Linux.

### 0.7 Modelo carregado entre falas (`keep_alive`)

- Problema confirmado: o Ollama descarrega o modelo após 5 min sem uso. Recarga
  medida hoje: **16 s** (a frio) e **4,1 s** (arquivo em cache do SO).
- Primeira tentativa: variável de usuário `OLLAMA_KEEP_ALIVE=24h` + reiniciar o
  Ollama. **Bloqueada pelo controle de permissões do agente** (alteração persistente
  do sistema + encerrar processos). Isso levou a uma solução melhor, dentro do
  repositório e sem mexer na máquina.
- Teste manual: o endpoint OpenAI do Ollama (`/v1/chat/completions`) **aceita**
  `"keep_alive"` no corpo. `ollama ps` passou de "4 minutes from now" para "24 hours
  from now".
- Implementação (mudança no código original):
  - `app/services/translation_service.py`: no formato `openai_chat`, envia
    `keep_alive` **só se estiver configurado**. Provedores OpenAI reais poderiam
    rejeitar o campo, então o comportamento original fica intacto por padrão.
  - Chave `translation.keep_alive: "${TRANSLATION_KEEP_ALIVE}"` no
    `config.yaml.example`. Como os provedores herdam as chaves da seção
    `translation`, vale para `qwen3` e `translategamma`, e cada provedor pode
    sobrescrever.
  - `TRANSLATION_KEEP_ALIVE=24h` no `.env.example`, repassada ao container no
    `docker-compose.yml` (o container só recebe as variáveis listadas ali).
  - 4 testes novos em `tests/test_translation_detailed.py`: ausente por padrão;
    `${VAR}` não resolvida = ausente; herdado pelo provedor roteado; provedor
    sobrescreve.
- Verificação: modelo descarregado (`keep_alive: 0`) → recarregado sem o campo (4
  min) → uma tradução pelo `TranslationService` → `ollama ps` mostra 24 h.
- Curiosidade: depois que um `keep_alive` longo foi definido, requisições **sem** o
  campo não reduziram o prazo. Mesmo assim, enviamos em toda requisição para não
  depender desse comportamento.

### 0.5 Imagens Docker e `docker compose up`

- Docker Desktop iniciado (estava parado); WSL2 com 7,4 GB e 16 CPUs, sem
  `.wslconfig`.
- Build **um serviço por vez** (`docker compose build <serviço>`), todos sem erro:

  | Serviço | Imagem | Tamanho | Tempo de build |
  |---|---|---|---|
  | `tts` (Piper) | `polytalk-tts` | 1,11 GB | 93 s |
  | `supertonic-tts` | `polytalk-supertonic-tts` | 963 MB | 78 s |
  | `stt` (faster-whisper, CPU, `small`) | `translator-room-stt` | **7,98 GB** | **540 s** |
  | `polytalk` (app) | `translator-room-polytalk` | 287 MB | 29 s |

- Vozes do Piper: em vez das 15 do `tts/setup-voices.sh`, baixadas só
  `zh_CN-huayan-medium` (necessária) e `en_GB-jenny_dioco-medium` (a voz padrão que o
  serviço carrega ao iniciar). Ficam em `tts/voices/`, já ignorado pelo
  `tts/.gitignore`. Comando (Git Bash):
  `MSYS_NO_PATHCONV=1 docker run --rm --entrypoint python -v "$(pwd -W)/tts/voices:/data" polytalk-tts:latest -m piper.download_voices --data-dir /data zh_CN-huayan-medium`
- **Problema: `supertonic-tts` em loop de reinício** (código 255,
  `exec /app/entrypoint.sh: no such file or directory`). Causa: `core.autocrlf=true`
  no Windows gravou o `entrypoint.sh` com CRLF, e o shebang virou `#!/bin/sh\r`.
  - Correção: `.gitattributes` novo com `*.sh text eol=lf` e `Dockerfile text
    eol=lf`; checkout dos 6 arquivos refeito (sem alterações locais) e
    `supertonic-tts` reconstruído.
  - **Lição:** uma checagem anterior com `grep -c $'\r'` no Git Bash disse "0 CR" e
    estava errada. `git ls-files --eol` é a forma confiável (`w/crlf`).
- Estado final: os 4 serviços `running`; `GET :8000/health` (STT) 200, `GET
  :9000/api/health` 200, TTS de pé (405 em `GET /`, rota só POST). De dentro do
  container `polytalk`, `http://host.docker.internal:11434/api/version` responde.
- Primeira subida do Supertonic baixa 26 arquivos do HuggingFace (sem token; aviso
  de limite de taxa, sem erro).
- Memória: há outros containers do usuário rodando no mesmo Docker (≈1,3 GB, de
  outros projetos). Os 4 do PolyTalk ocupam ≈1 GB parados (STT 383 MB, TTS 482 MB).

### 0.6 Modo `conversation` real (teste sintético)

- `config/config.yaml` local com `mock_mode: false` em `whisper`, `translation` e
  `tts`; `docker compose restart polytalk` para recarregar.
- O teste "falando PT e ZH" exige uma pessoa no microfone. O agente fez um **teste
  sintético de ponta a ponta** no lugar: a fala foi gerada com as vozes da própria
  pilha (Supertonic `F1` para PT, Piper `zh_CN-huayan-medium` para ZH), reamostrada
  para 16 kHz Int16 (o mesmo formato do `audio-recorder.js`) e enviada em pedaços
  de 100 ms em tempo real pelo WebSocket
  `mode=conversation&source_language=pt&target_language=zh`, com 6 s de silêncio
  entre as falas. Script fora do repositório (`conversation_e2e.py` no scratchpad do
  agente), candidato a virar a ferramenta da 1.2.
- Resultado: **funciona nas duas direções**, com o idioma detectado corretamente
  em todos os turnos e a voz certa em cada direção.

  | Turno | Fala sintetizada | Transcrição (Whisper `small`, CPU) | Tradução | Fim da fala → `tts` |
  |---|---|---|---|---|
  | PT→ZH | Oi, tudo bem? Você sabe onde fica a estação de metrô mais próxima? | (idêntica) | 你好，一切都好吗？你知道最近的地铁站是哪一个吗？ | 5,01 s |
  | ZH→PT | 你好，很高兴认识你。请问洗手间在哪里？ | 你好很高興認識你,請問洗手間在哪裡? | Olá, é um prazer conhecê-lo. Onde fica o banheiro? | 5,31 s |
  | PT→ZH | Amanhã vamos nos reunir às três da tarde para fechar o contrato. | (idêntica) | 明天下午三点，我们将见面，正式签订合同。 | 3,60 s |
  | ZH→PT | 这个价格有点贵，能便宜一点吗？ | 這個價格有點**歸**能**貶易**一點嗎? | Este preço está um pouco alto, **não acha?** | 4,95 s |

- Achados para a Etapa 1:
  - **O Whisper devolve o chinês em caracteres tradicionais** (高興, 這個, 哪裡) e
    errou 贵→歸 e 便宜→貶易 no turno 4, o que mudou o sentido da tradução. Entra na
    1.3 (`small` × `medium`). Possíveis ajustes: `STT_INITIAL_PROMPT` em
    simplificado ou conversão para simplificado antes da tradução.
  - **Latência de 3,6 a 5,3 s**, acima da meta de 3 s, com o STT nos padrões
    (`STT_STREAM_CHUNK_SECONDS=3.0`, `STT_PAUSE_FLUSH_SECONDS=1.2`,
    `STT_EMIT_INTERVAL_SECONDS=4.5`). A medição é aproximada (o instante em que a
    mensagem `tts` chega, não o início da reprodução). Base para a 1.2 e a 1.4.
- **Pendente:** teste com uma pessoa falando PT e ZH no navegador do notebook
  (`http://127.0.0.1:9000`, modo conversa). O chinês (`zh`) **está** nos seletores
  de origem e destino da tradução. O "não tem chinês" registrado em 2026-11-20 vale
  só para os idiomas **da interface** (`app/locales/`, 13 catálogos sem `zh`).

### Etapa 0 – uso do agente e pendências

- **Como o agente foi usado:** Claude Code executou a etapa inteira a partir do
  arquivo da etapa (importação, configuração, builds, testes e diagnóstico), com um
  commit por subtarefa. Ordem real: 0.1 → 0.2 → 0.3 → 0.4 → 0.8 → 0.7 → 0.5 → 0.6.
  A 0.8 e a 0.7 foram adiantadas enquanto o Docker Desktop iniciava e as imagens
  eram construídas.
- **O que exigiu atenção / correção:**
  - O controle de permissões bloqueou a alteração persistente do sistema
    (`OLLAMA_KEEP_ALIVE` + reiniciar o Ollama). O agente trocou por uma solução no
    código (0.7), que ficou mais portátil e testável.
  - O agente fez uma checagem de CRLF que deu resultado errado e só percebeu quando
    o container quebrou (0.5).
  - A extensão do navegador não estava conectada; a 0.4 foi verificada por HTTP e
    WebSocket, não visualmente.
- **Pendências para fechar a etapa** (antes do PR para a `main` e da tag
  `etapa-0-concluida`):
  1. Abrir `http://127.0.0.1:9000` no navegador e conferir a interface (0.4).
  2. Teste falado PT↔ZH por uma pessoa (0.6).
  3. Revisão das mudanças de código por um integrante:
     `app/services/translation_service.py`, `tests/test_translation_detailed.py`,
     `docker-compose.yml`, `.gitattributes`.
