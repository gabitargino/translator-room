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
  1. ~~Abrir `http://127.0.0.1:9000` no navegador e conferir a interface (0.4).~~
     Feito.
  2. ~~Teste falado PT↔ZH por uma pessoa (0.6).~~ Feito.
  3. Revisão das mudanças de código por um integrante (no PR):
     `app/services/translation_service.py`, `tests/test_translation_detailed.py`,
     `docker-compose.yml`, `.gitattributes`.

### 0.4 e 0.6 – conferência humana

- Um integrante abriu `http://127.0.0.1:9000` no Chrome do notebook, com a pilha
  Docker no modo real (mocks desligados), e usou o modo **Conversation** com origem
  Portuguese e destino Chinese.
- Resultado relatado: **a interface carregou e traduziu nas duas direções** (PT→ZH
  e ZH→PT, com voz). Latência e erros de console não foram anotados; a medição
  formal fica para a Etapa 1 (1.2).
- Com isso, 0.4 e 0.6 estão concluídas, e a **Etapa 0 está concluída**. Falta o PR
  `etapa-0-preparacao` → `main`, com revisão do outro integrante, e a tag
  `etapa-0-concluida`.

## 2026-11-21 – Etapa 1 (branch `etapa-1-viabilidade`)

### 1.1 Conjunto de frases de teste

- Pasta nova [`bench/`](../bench/README.md), separada de `tools/benchmarks/` (que é
  do PolyTalk), para não misturar código nosso com o original.
- `bench/frases.tsv`: 10 frases em PT e 10 em ZH (reunião de negócios e viagem),
  com a tradução de referência de cada uma, para reaproveitar na 6.7. Incluem
  números, datas, preço e nome de cidade.
- `bench/audio/*.wav`: 16 kHz, mono, 16 bits, de 1,3 a 4,1 s, sem silêncio nas pontas;
  1,6 MB no total.
- **Desvio do plano:** o plano dizia "gravadas"; os áudios foram **sintetizados**
  com as vozes da própria pilha (Supertonic em PT, com 10 vozes alternadas; Piper
  `zh_CN-huayan-medium` em ZH, uma voz só). Isso permite regerar o conjunto e medir
  sem depender de alguém gravar. Em troca, a precisão medida é otimista. O README
  explica como trocar por gravações reais com o mesmo `id`.
- Conferência rápida pelo WebSocket do STT (Whisper `small`, CPU):
  - PT saiu correto (`pt-01` exato; `pt-04` escreveu "R$ 12,50" por extenso→número).
  - ZH errou de novo, como na 0.6: `zh-03` 贵→规; `zh-05` 三→散, em caracteres
    tradicionais (下個星期散下午3點).
  - A comparação da 1.3 precisa normalizar números e tradicional→simplificado
    antes de contar erros.
- O `tools/benchmarks/benchmark_stt.py` do PolyTalk não devolve texto com esses
  áudios: ele não manda silêncio depois da fala, e o STT só fecha a janela por
  pausa (`STT_PAUSE_FLUSH_SECONDS`) ou por tamanho. Os scripts de `bench/` mandam
  silêncio depois da fala, como o navegador faz.

### 1.2 Latência da configuração padrão (modo conversation)

- Script: `bench/medir_conversa.py`. Uma sessão `mode=conversation` pt↔zh recebe o
  áudio como o navegador manda (blocos de 2048 amostras, 128 ms, em tempo real),
  com as frases alternadas pt-01, zh-01, pt-02... O relógio parte do último bloco
  com fala. Resultado bruto: `bench/resultados/1.2-padrao.json`.
- Configuração: a do `.env.example` (`STT_PAUSE_FLUSH_SECONDS=1.2`, Whisper `small`
  CPU int8, Supertonic com 8 passos, `translategemma:4b` com `keep_alive`).
- 2 rodadas × 20 frases = 20 medidas por direção. Nenhuma falha, frase dividida ou
  direção errada (a detecção pt/zh acertou as 40).

Tempo desde o fim da fala (s), mediana / p95:

| Parte | PT→ZH | ZH→PT |
|---|---|---|
| Até a transcrição (espera de silêncio + STT) | 2,79 / 3,05 | 2,74 / 2,95 |
| Tradução (isolada) | 0,52 / 0,57 | 0,52 / 0,69 |
| Voz (isolada) | 0,12 / 0,31 (Piper zh) | 1,06 / 1,63 (Supertonic pt) |
| Download do áudio (isolado) | 0,02 / 0,02 | 0,01 / 0,03 |
| **Total até o áudio** | **3,46 / 3,84** | **4,38 / 5,06** |

- **Nenhuma direção cumpre a meta de 3 s.** A transcrição sozinha leva ~2,75 s,
  dos quais 1,2 s são espera de silêncio. Os ~1,5 s restantes são STT (a 1.3 vai
  separar inferência de fila).
- A voz em PT (Supertonic) custa ~1 s a mais que a voz em ZH (Piper): é a diferença
  entre as direções (1.6).
- A tradução dentro do app leva 0,52 s, contra 0,28–0,35 s medidos isoladamente no
  Ollama. A diferença é o prompt do PolyTalk e o processamento do app; não é a
  maior parte do problema.
- O tempo de transcrição quase não depende do tamanho da frase (1,4 s a 4,1 s de
  fala dão 2,65 a 3,24 s): o custo é a espera fixa mais o processamento.
- **Correção no script durante a medição:** a primeira versão media o download
  depois de esperar 1,5 s sem mensagens e deu "envio = 1,5 s". O download real
  leva 0,01–0,03 s; o script agora soma só o tempo do download à chegada da
  mensagem `tts`.
- **Limitações:** silêncio digital (o microfone real tem ruído; o script aceita
  `--ruido-dbfs`), servidor e cliente no mesmo computador (sem Wi-Fi) e o início
  da reprodução no navegador não entra na conta.
- Qualidade observada (para a 1.3): no ZH, o STT trocou 贵→规 (zh-03, a tradução
  perdeu "caro") e 三→散 (zh-05, a tradução perdeu "quarta-feira"). No PT, a
  transcrição saiu certa, mas `pt-07` virou "a que distância fica" na tradução
  (erro do tradutor). A pontuação do STT em ZH às vezes cai no meio da frase.

### 1.3 Precisão do STT: modelos em CPU e GPU

- Script: `bench/medir_stt.py`, direto no WebSocket do STT, uma conexão por frase,
  `emit_policy=pause` como no modo conversation. Mede nos dois modos de idioma:
  **fixo** (o idioma é informado) e **auto** (detecção restrita a pt/zh, que é o
  que o modo conversation faz).
- Métrica: CER em ZH e WER em PT, depois de normalizar (tradicional→simplificado
  com `opencc-python-reimplemented`, instalado só na `.venv`; algarismos→numerais;
  两→二; sem pontuação). O tempo é medido do envio do silêncio final até o texto;
  como o áudio vai sem esperar o tempo real, o tempo é quase só inferência.
- **GPU no Docker:** a imagem do STT (`nvidia/cuda:12.2.2-cudnn8`) tem cuDNN 8 e o
  `ctranslate2` instalado é o 4.9. Eu esperava que isso falhasse na GPU, mas um
  teste com `small` em `cuda` funcionou. Não foi preciso mudar a imagem.
- Os modelos foram testados num container temporário (`stt-gpu-teste`, porta 8001,
  mesmas variáveis do STT atual), com o tradutor carregado na GPU ao mesmo tempo.

Resultados (1 rodada, 10 frases por idioma e modo; tempo = mediana em s):

| Modelo | ZH exatas (fixo / auto) | Erro ZH | PT exatas | Tempo | Erros em ZH |
|---|---|---|---|---|---|
| `small` CPU int8 (padrão) | 8 / 8 | 1,5% | 10 / 10 | 1,55–1,80 | 贵→规, 三→散 (+ tradicional) |
| `small` GPU fp16 | 8 / 8 | 1,5% | 10 / 10 | 0,43 | os mesmos |
| **`medium` GPU fp16** | **9 / 9** | **0,8%** | 10 / 10 | **0,68** | 贵→归 |
| `medium` GPU int8_float16 | 8 / 9 | 0,8–2,0% | 9 / 10 | 0,65 | 贵→归, 洗→吸; PT: metrô→metro |
| `large-v3-turbo` GPU int8_float16 | 7 / 7 | 2,7–4,0% | 10 / 10 | 0,58 | 洗手间→携手间/键, 贵→归, 下个→下隔 |

- **Primeira escolha (revista abaixo): `medium` fp16 na GPU.** Foi o que mais acertou em chinês e corta
  ~1 s por frase em relação ao padrão. O `small` na GPU seria ainda mais rápido
  (0,43 s), mas mantém o erro 三→散, que mudou o sentido de uma tradução na 1.2.
  O turbo em int8 foi rápido, mas errou palavras comuns (洗手间).
- O erro 贵→归/规 aparece em **todos** os modelos. Provavelmente é a pronúncia da
  voz sintética do Piper, não do STT. Confirmar com gravação real.
- O `small` em CPU deu 1,55 s numa medição e 1,7–1,8 s noutra; o processador é
  compartilhado com os outros containers do notebook. Uma medição feita enquanto
  o turbo era baixado (1,9–2,0 s) foi descartada.
- **Idioma: manter a detecção automática (pt/zh).** Ela acertou 100% em todos os
  modelos, inclusive em frases de 1,3 s, e a diferença de tempo para o modo fixo é
  desprezível. Isso preserva o sinal de idioma para o filtro da 2.7. Fixar o idioma
  por participante continua como plano B, caso a fala real dê erros de detecção.
- A primeira frase depois de carregar o modelo na GPU demora mais (1,9–3,6 s,
  aquecimento). Isso aparece no p95 do modo fixo, que é medido primeiro.
- **Aplicado na pilha** (o modelo foi trocado depois para `small`, ver a revisão):
  - `.env.example` (e `.env` local): `STT_MODEL=medium`, `STT_DEVICE=cuda`,
    `STT_COMPUTE_TYPE=float16`, `STT_MODEL_WORKERS=1` (uma cópia do modelo na GPU de
    6 GB, que é dividida com o tradutor);
  - `COMPOSE_FILE=docker-compose.yml;docker-compose.gpu.yml`, para que o
    `docker compose up` simples já use a GPU;
  - `docker-compose.gpu.yml`: volume `stt_models` para o cache do Hugging Face. Sem
    ele, o `medium` seria baixado de novo a cada recriação do container, porque o
    build da imagem não tem GPU e só embute o `small`.
- Quanto de VRAM sobra com os dois modelos carregados: o `nvidia-smi` no WSL não
  mostra o uso por processo, e o total varia com os programas abertos no Windows
  (4,1 a 5,7 GB de 6,1 GB durante os testes). O tradutor continuou 100% na GPU
  (`size_vram` = `size` no `/api/ps`).

#### 1.3 – revisão da escolha: `small` fp16 na GPU

Com o `medium` fp16 aplicado, a medição de ponta a ponta
(`bench/resultados/1.3-medium-gpu.json`) **não melhorou**: PT→ZH 3,44 s, ZH→PT
4,67 s. A transcrição ficou ~0,6 s mais rápida, mas a tradução passou de 0,52 s
para 0,94–1,0 s, e a voz em PT de 1,06 s para 1,48 s.

Investigação:

1. Disputa de CPU? Não: `docker stats` durante a conversa mostrou os containers
   ociosos entre as frases.
2. Tradução sozinha com o STT carregado, mas parado: 0,22 s, igual a antes.
3. Tradução logo depois de uma inferência do STT: lenta tanto com o STT na GPU
   quanto em CPU (0,44–0,66 s). Um teste só com o Ollama mostrou o motivo: depois
   de 4 s parada, a GPU reduz o clock, e a mesma frase leva 0,42 s, contra 0,2 s
   em sequência. Isso explica os 0,52 s da 1.2, mas não os 0,95 s.
4. O log do Ollama (`server.log`, uma linha por pedido) confirmou que o próprio
   Ollama ficou 2× mais lento: **0,40–0,72 s por pedido na 1.2 contra 0,86–1,32 s
   com o `medium` na GPU**, mesmo com as 35/35 camadas na GPU.
5. Com modelos menores na GPU, o Ollama voltou a **0,20–0,48 s**:

| STT na GPU | PT→ZH (mediana / p95) | ZH→PT (mediana / p95) | Ollama por pedido |
|---|---|---|---|
| `small` CPU int8 (1.2, referência) | 3,46 / 3,84 | 4,38 / 5,06 | 0,40–0,72 s |
| `medium` fp16 | 3,44 / 3,89 | 4,67 / 5,71 | 0,86–1,32 s |
| `medium` int8_float16 | 2,47 / 5,76* | 3,65 / 4,18 | 0,20–0,65 s |
| **`small` fp16** | **2,20 / 2,32** | **3,49 / 4,28** | 0,20–0,42 s |

\* a primeira frase depois de recriar o container (aquecimento).

Conclusão: com o `medium` fp16 (~1,5 GB), a VRAM de 6 GB fica no limite junto com
o tradutor (2,9 GB) e com o Windows. O driver (WDDM) passa a mover memória entre a
GPU e a RAM, e o tradutor sofre. Isso não aparece no `size_vram` do Ollama.

Precisão **dentro do app** (transcrições das medições de ponta a ponta, mesmo
normalizador): todos os modelos erram **as mesmas duas frases em ZH** (zh-03
贵→归/规, zh-05 三→散). Em PT, todos acertam tudo, exceto o `medium` int8 (pt-07
metrô→metro). A vantagem do `medium` no teste direto do STT (9/10) não se repete no
app. A diferença provável está no áudio: no app há 0,2 s de silêncio antes da fala
e o envio é em tempo real. Para a escolha, vale o caminho real.

**Escolha final: `small` fp16 na GPU** (`STT_MODEL=small`, `STT_DEVICE=cuda`,
`STT_COMPUTE_TYPE=float16`, `STT_MODEL_WORKERS=1`). Tem a mesma precisão do padrão
no app, inferência de 0,43 s e pouca VRAM, e o tradutor fica rápido.
**PT→ZH já cumpre a meta (2,20 s); ZH→PT não (3,49 s)**, porque a voz em PT
(Supertonic, ~1,3 s) é o que mais pesa agora (1.6). A espera de silêncio (1,2 s) é
a outra parte grande (1.4).

Lições para o relatório: medir cada peça isolada não bastou. O `medium` parecia
melhor nas duas métricas isoladas (precisão no STT, tradução sozinha) e piorou o
sistema. Foi a medição de ponta a ponta que mostrou o problema.

### 1.4 Espera de silêncio e janelas do STT

- **Janelas:** no modo conversation, o PolyTalk usa `emit_policy=pause`, e o STT
  só fecha a frase por pausa (`STT_PAUSE_FLUSH_SECONDS`) ou por falta de áudio
  (`STT_IDLE_FLUSH_SECONDS`, que não ocorre com o microfone aberto). O tamanho da
  janela (`STT_STREAM_CHUNK_SECONDS`) e as regras de emissão (`STT_EMIT_*`) só
  valem no modo live. **O único ajuste que importa aqui é a espera de silêncio.**
- **Bug encontrado e corrigido** (commit `2ec42ed`):
  - Em `stt/app/main.py`, o contador `trailing_silence_bytes` não zerava quando a
    fala voltava, então pausas internas se somavam. Uma frase com hesitação de
    0,9 s (abaixo da espera de 1,2 s) fechava cedo, e o corte do silêncio final
    apagava o fim: "o prazo está muito curto" virou "o prazo está morto".
  - O que revelou o bug foi a primeira varredura: com hesitação, a latência
    ficava *menor*, o que não faz sentido.
  - Correção de uma linha (zerar o contador quando a voz volta) e teste novo
    (`test_stt_stream_internal_pause_does_not_count_as_trailing_silence`), que
    falhava antes da correção. Suíte: 459 passam; as 4 falhas são as mesmas da
    0.8, só no Windows.
  - A primeira varredura foi descartada e refeita.
- Script: `bench/medir_conversa.py` ganhou `--pausa-interna`. A opção estica a
  maior pausa dentro da frase (entre 15% e 85% dela, normalmente a vírgula) para
  simular hesitação. 15 das 20 frases têm onde esticar.

Varredura com o STT `small` fp16 na GPU (1 rodada, 10 frases por direção; tempo
até o áudio, mediana / p95 em s):

| Espera | Áudio | PT→ZH | ZH→PT | Divididas | Erro PT | Erro ZH |
|---|---|---|---|---|---|---|
| 1,2 s | original | 2,12 / 2,23 | 3,08 / 3,71 | 0 | 0% | 1,5% |
| 1,2 s | hesitação 0,5 s | 2,15 / 2,28 | 3,11 / 3,65 | 0 | 0% | 1,5% |
| 0,8 s | original | 1,70 / 1,93 | 2,72 / 3,17 | 0 | 0% | 1,5% |
| 0,8 s | hesitação 0,5 s | 1,75 / 1,85 | 2,64 / 3,34 | 0 | 0% | 1,5% |
| 0,6 s | original | 1,42 / 1,55 | 2,42 / 2,99 | 0 | 0% | 1,5% |
| 0,6 s | hesitação 0,5 s | 1,46 / 1,64 | 2,45 / 3,24 | 0 | 0% | 1,5% |
| 0,4 s | original | 1,31 / 1,46 | 2,23 / 3,17 | 0 | 0% | 1,5% |
| 0,4 s | hesitação 0,5 s | 1,35 / 1,42 | 2,40 / 3,00 | 0 | 0% | 1,5% |

- Cada 0,1 s a menos de espera tira ~0,1 s da latência, até 0,6 s. De 0,6 para
  0,4 s, o ganho cai (o bloco de áudio tem 128 ms).
- Os erros são sempre zh-03 e zh-05 (os mesmos da 1.3). Com hesitação, aparece
  zh-08 (样品→央品), porque o script inseriu a pausa no meio da palavra. É um
  efeito do script, não da espera.
- **A hesitação de 0,5 s não dividiu frases nem com espera de 0,4 s.** A pausa
  inserida fica, na prática, com ~0,4 s abaixo do limiar do STT
  (`STT_SILENCE_RMS_THRESHOLD=0.003`), contados em blocos de 128 ms. Teste direto
  no STT com espera de 0,8 s (`pt-08`): pausa interna de 0,7 s mantém a frase
  inteira; de 1,0 s ou 1,3 s, divide em duas falas ("Eu concordo com a proposta." e
  depois a frase toda). A primeira metade sai enquanto a pessoa ainda fala.
- **Escolha: `STT_PAUSE_FLUSH_SECONDS=0.8`** (em `.env.example` e no `.env`). Fica
  abaixo de 3 s nas duas direções e tolera hesitações de até ~0,7 s. A 0,6 s
  ganharia mais 0,3 s, mas a fala real tem pausas de 0,5–1 s entre trechos da
  frase, e cada divisão vira uma tradução separada, sem o contexto da outra
  metade. Fica como opção se a voz em PT (1.6) não melhorar.

Medição final com a configuração escolhida (`small` fp16 GPU, espera 0,8 s;
`bench/resultados/1.4-final.json`, 2 rodadas, 20 medidas por direção):

| Parte (mediana / p95, s) | PT→ZH | ZH→PT |
|---|---|---|
| Até a transcrição (espera + STT) | 1,35 / 1,50 | 1,37 / 1,49 |
| Tradução (isolada) | 0,22 / 0,31 | 0,26 / 0,37 |
| Voz (isolada) | 0,10 / 0,13 (Piper) | 1,04 / 1,53 (Supertonic) |
| Download do áudio | 0,02 / 0,02 | 0,02 / 0,03 |
| **Total até o áudio** | **1,67 / 1,89** | **2,75 / 3,27** |

Em relação à 1.2 (padrão): PT→ZH 3,46 → 1,67 s e ZH→PT 4,38 → 2,75 s. Nenhuma
falha nem direção errada.

Com hesitação de 1,0 s (`1.4-final-hesitacao-1.0.json`), 12 das 20 frases foram
divididas, como esperado: pausa maior que a espera. A latência até o áudio da
última parte ficou em 1,41 s (PT→ZH) e 2,47 s (ZH→PT). Dividir não atrasa, mas
cada parte é traduzida sem a outra.

**Risco descoberto: ruído de fundo.**

- O STT considera silêncio o bloco de 128 ms com RMS abaixo de 0,003
  (`STT_SILENCE_RMS_THRESHOLD`, ≈ −50 dBFS). Medi com ruído gaussiano no lugar do
  silêncio digital (`--ruido-dbfs`, 4 frases):
  - **−60 dBFS:** normal (1,85–3,24 s até o áudio).
  - **−45 dBFS:** **nenhuma frase transcrita.** O silêncio nunca é detectado, a
    pausa nunca fecha a frase e, com o microfone aberto, a espera por
    inatividade (3 s) também nunca dispara.
- O navegador pede `noiseSuppression` e `echoCancellation` ao abrir o microfone
  (`app/static/js/audio-recorder.js`), e o teste humano da 0.6 funcionou com o
  microfone do notebook. Então, na prática, o fundo ficou abaixo do limiar. Mas
  celulares e salas variam.
- **Pendência para a Etapa 3 (celulares) e a Etapa 6 (testes):** medir o nível de
  fundo real dos celulares. Se passar de −50 dBFS, subir
  `STT_SILENCE_RMS_THRESHOLD` ou trocar a detecção por RMS pelo VAD (Silero),
  que o faster-whisper já tem.

### 1.5 Duas falas simultâneas

- Script: `bench/medir_concorrencia.py`. Abre duas sessões conversation
  independentes (A e B), como dois participantes. Em cada passo, as duas começam a
  falar no mesmo instante: A fala pt-N e B fala zh-N. As frases têm tamanhos
  diferentes, então terminam em momentos diferentes, mas o processamento se
  sobrepõe. Configuração final da 1.4 (`small` fp16 GPU, `STT_MODEL_WORKERS=1`,
  `STT_TRANSCRIBE_WORKERS=2`, espera de 0,8 s). 2 rodadas, 20 medidas por direção.
  Resultado: `bench/resultados/1.5-2-falas-mw1.json`.

| Parte (mediana / p95, s) | PT→ZH 1 sessão | PT→ZH 2 sessões | ZH→PT 1 sessão | ZH→PT 2 sessões |
|---|---|---|---|---|
| Até a transcrição | 1,35 / 1,50 | 1,47 / 1,69 | 1,37 / 1,49 | 1,36 / 1,50 |
| Tradução | 0,22 / 0,31 | 0,27 / 0,38 | 0,26 / 0,37 | 0,35 / 0,50 |
| Voz | 0,10 / 0,13 | 0,23 / 0,62 | 1,04 / 1,53 | 1,56 / 2,68 |
| **Total até o áudio** | **1,67 / 1,89** | **2,14 / 2,46** | **2,75 / 3,27** | **3,32 / 4,34** |

- Nenhuma falha: as duas sessões receberam tudo, na direção certa.
- **O gargalo sob concorrência é a voz, não o STT.** O Supertonic (PT) e o Piper
  (ZH) rodam em CPU e usam vários núcleos cada um (o `docker stats` mostrou 240–
  335% numa síntese). Quando os dois sintetizam ao mesmo tempo, a voz em PT
  ganha +0,5 s na mediana e +1,1 s no p95.
- O STT com um modelo só (`STT_MODEL_WORKERS=1`) quase não sofreu (+0,0–0,1 s):
  a inferência na GPU leva ~0,4 s, então a segunda fala espera pouco. Não vale
  subir para 2 modelos e gastar mais VRAM. O tradutor (fila do Ollama) também
  sofreu pouco (+0,05–0,1 s).
- Com duas falas simultâneas, **ZH→PT passa da meta (mediana 3,32 s)**. Na sala,
  falas simultâneas devem ser exceção (as pessoas se revezam), mas o p95 de 4,3 s
  mostra que a voz em PT é o próximo ponto a atacar (1.6).

### 1.6 Tempo de síntese de voz

- Script: `bench/medir_tts.py`, direto nos serviços. Sintetiza a coluna
  `referencia` (o texto que o TTS recebe numa conversa) com os parâmetros do app:
  ZH no Piper (`zh_CN-huayan-medium`) e PT no Supertonic (voz F1). Para o
  Supertonic, testa 8 (padrão), 4 e 2 passos. 3 rodadas × 10 frases. Resultado:
  `bench/resultados/tts-1.6.json`. Os áudios ficam em `bench/resultados/tts-1.6/`,
  fora do git, para serem ouvidos.
- Inteligibilidade estimada com `bench/inteligibilidade_tts.py`: transcreve a voz
  gerada com o STT e calcula o WER contra o texto. Isso mede se o Whisper entende,
  não se a voz soa natural.

| Voz | Tempo (mediana / p95, s) | Tempo / duração do áudio | WER pelo STT | Frases exatas |
|---|---|---|---|---|
| Piper ZH | 0,15 / 0,23 | 0,06 | — | — |
| Supertonic PT, 8 passos (padrão) | 1,48 / 1,90 | 0,37 | 3,8% | 8/10 |
| **Supertonic PT, 4 passos** | **0,83 / 1,10** | 0,20 | 3,5% | 8/10 |
| Supertonic PT, 2 passos | 0,51 / 0,63 | 0,13 | 40,7% | 5/10 |

- O Piper é 10× mais rápido que o Supertonic. Por isso ZH→PT (voz em PT) é sempre
  a direção mais lenta.
- Com 4 passos, a voz é tão inteligível quanto com 8 e leva quase metade do tempo.
  Com 2, várias frases ficaram ininteligíveis ("Com licença, onde fica o
  banheiro?" virou "Conheça em Sanchiko Banyu").
- Os erros com 8 e 4 passos são de nome e número ("Sangai/Shanghai" por Xangai,
  "200" por "duzentos", porque o normalizador só escreve por extenso até 99), não
  de pronúncia.
- **Escolha: `SUPERTONIC_TTS_STEPS=4`** (em `.env.example` e no `.env`).
  **Pendente: um integrante ouvir** `bench/resultados/tts-1.6/*-pt-8p.wav` contra
  `*-pt-4p.wav` e confirmar que a voz continua natural. Para gerar os arquivos:
  `python bench/medir_tts.py --rotulo 1.6 --passos 8,4,2`.
- Dentro do app, a voz em PT passou de 1,04 para 0,75 s na mediana (`1.6-final`).
  O ganho é menor que no teste direto, porque as traduções reais são mais curtas
  que as referências.
- Aquecimento: depois de reiniciar o container `polytalk`, as duas primeiras vozes
  em ZH levaram 2,1 s e 1,3 s, contra 0,1 s nas demais (provavelmente a busca da
  lista de vozes do Piper, que o app guarda por 1 h, e as conexões novas). Fica
  para a Etapa 5: aquecer os serviços ao iniciar.

### Portão da Etapa 1: decisão

Medição com a configuração final (`bench/resultados/1.6-final.json`, 2 rodadas, 20
medidas por direção, uma sessão; `1.6-final-2-falas.json`, duas falas
simultâneas, 1 rodada):

| Configuração | PT→ZH mediana / p95 | ZH→PT mediana / p95 |
|---|---|---|
| Padrão (1.2): `small` CPU, espera 1,2 s, Supertonic 8 passos | 3,46 / 3,84 | 4,38 / 5,06 |
| **Final, uma fala** | **1,85 / 2,96** | **2,45 / 2,94** |
| Final, duas falas simultâneas | 2,01 / 2,54 | 2,64 / 3,53 |

Para onde foi o tempo (final, uma fala, medianas):

| Parte | PT→ZH | ZH→PT |
|---|---|---|
| Espera de silêncio (0,8 s) + STT `small` na GPU | 1,42 | 1,40 |
| Tradução | 0,24 | 0,29 |
| Voz | 0,14 (Piper) | 0,75 (Supertonic, 4 passos) |
| Download do áudio | 0,02 | 0,02 |

**Decisão: o portão passou.** A mediana fica abaixo de 3 s nas duas direções, com
folga (1,85 e 2,45 s), e o p95 também. A Etapa 2 está liberada.

Configuração adotada (`.env.example`):

- `STT_MODEL=small`, `STT_DEVICE=cuda`, `STT_COMPUTE_TYPE=float16`,
  `STT_MODEL_WORKERS=1`, com `COMPOSE_FILE` incluindo `docker-compose.gpu.yml`;
- `STT_PAUSE_FLUSH_SECONDS=0.8`;
- `SUPERTONIC_TTS_STEPS=4`;
- correção do contador de silêncio do STT (`stt/app/main.py`).

Ressalvas que seguem para as próximas etapas:

1. **Fala sintética e silêncio digital.** A precisão e o fechamento das frases
   foram medidos em condições ideais. Com ruído de fundo de −45 dBFS, o STT não
   fecha nenhuma frase (1.4). Medir com os celulares (Etapas 3 e 6).
2. **Ouvir a voz em PT com 4 passos** (1.6), antes de considerar a escolha final.
3. **Chinês:** o STT ainda erra zh-03 (贵) e zh-05 (三→散) e devolve caracteres
   tradicionais em parte das frases. Isso não afeta a latência, mas afeta a
   tradução (1.2). Avaliar na 6.7 com gravações reais.
4. **Aquecimento:** a primeira fala depois de reiniciar o STT ou o app é mais lenta
   (1,3–3,6 s a mais). Tratar na Etapa 5.
5. **Rede:** tudo foi medido no próprio notebook. O Wi-Fi até os celulares entra na
   Etapa 4/5.
6. **VRAM:** o `medium` mostrou que STT e tradutor disputam a GPU de 6 GB. Qualquer
   modelo novo na GPU precisa de uma medição de ponta a ponta, não só isolada.

### Etapa 1 – uso do agente

- **Executado pelo agente:**
  - as 6 subtarefas, com um commit cada, mais o commit da correção do STT;
  - 6 scripts de medição em `bench/` (só biblioteca padrão, mais `websockets` e
    `opencc` opcional);
  - todas as medições, com os resultados brutos versionados em
    `bench/resultados/`;
  - o diagnóstico da lentidão com o `medium` (log do Ollama);
  - a descoberta e a correção do bug do contador de silêncio, com teste.
- **Erros do agente corrigidos no caminho:**
  - o script de latência media o download depois de uma espera (deu 1,5 s em vez de
    0,02 s);
  - a hipótese de que o cuDNN 8 impediria a GPU estava errada;
  - a primeira escolha do `medium` foi feita com medições isoladas e revista com a
    de ponta a ponta;
  - um caractere nulo entrou num script por escape errado no shell;
  - a medição do `small` em CPU foi repetida porque rodou junto com um download.
- **Pendências humanas:** ouvir a voz com 4 passos (1.6); gravar frases reais, se
  o grupo quiser medir a precisão fora do caso ideal; revisar o PR, em especial a
  mudança em `stt/app/main.py`.

## 2026-11-21 – Etapa 2 (branch `etapa-2-salas-servidor`)

### 2.1 Projeto das salas

As salas são um **módulo novo**, `app/rooms/`. Do código original só mudaram três
linhas em `app/main.py` (incluir as rotas e ligar/desligar a limpeza) e dois
valores padrão no `docker-compose.yml`.

| Arquivo | Papel |
|---|---|
| `settings.py` | Configuração `ROOM_*` lida do ambiente |
| `models.py` | `Room`, `Participant` e `RoomManager` (ciclo de vida, avisos, áudios) |
| `session.py` | Sessão de um participante: fluxo de STT e fila de falas |
| `routing.py` | Filtro de conversa cruzada e entrega por idioma de escuta |
| `timing.py` | Marcas de tempo por fala e estimativa do fim da fala |
| `router.py` | Rotas REST e WebSocket |

**Modelo de dados.**

- **Sala:** código de 5 caracteres (alfabeto sem 0/O/1/I/L, para ditar em voz
  alta), criação, participantes, `empty_since`, lista dos áudios gerados e um
  contador de falas. O estado vem do número de participantes: `empty` (0),
  `waiting` (1) e `active` (2 ou mais).
- **Participante:** id, nome (até 40 caracteres), idioma de fala, idioma de escuta
  (por padrão, igual ao de fala), silenciado ou não, e a função de envio da
  conexão. Os envios passam por um `asyncio.Lock`, porque várias tarefas (o worker
  de cada pessoa que fala) podem mandar mensagens à mesma conexão ao mesmo tempo.

**Protocolo.**

| Rota | O que faz |
|---|---|
| `POST /api/rooms` | Cria a sala: `{"room": "K4YUS", "state": "empty", "ws_url": ...}` |
| `GET /api/rooms/{code}` | Estado e participantes (404 se não existe) |
| `WS /api/ws/rooms/{code}?name=&speak=&listen=` | Conexão do participante |

O celular envia áudio PCM 16 kHz mono 16 bits, o mesmo formato do
`/api/ws/translate`. Ele recebe:

| Mensagem | Para quem |
|---|---|
| `joined` | Quem entrou (com o próprio id) |
| `participant_joined`, `participant_left`, `room_state` | Todos (2.8) |
| `self_transcript` | Só quem falou: a própria transcrição, sem tradução nem áudio |
| `utterance_ignored` | Só quem falou: fala descartada pelo filtro (2.7) |
| `room_translation`, depois `room_tts` | Só os ouvintes do idioma de destino |
| `room_error`, `error` | Erros de tradução/voz (ouvintes) ou de STT (quem fala) |

Controle aceito: `mute`/`pause`, `unmute`/`resume`, `end`, `ping` (responde
`pong`) e `playback_started` (com `utterance_id`, para a Etapa 5). Erros de
entrada fecham a conexão com códigos próprios: 4404 (sala não existe), 4409
(cheia) e 4400 (idioma inválido).

**Decisões.**

- **Um worker do app (`APP_WORKERS=1`).** As salas ficam na memória do processo.
  O PolyTalk subia 3 workers do gunicorn; com isso, duas pessoas da mesma sala
  podiam cair em processos diferentes e não se enxergar. O padrão no
  `docker-compose.yml` passou para 1. O trabalho pesado está no STT, no Ollama e
  nas vozes, que são outros processos, então um worker não limita a v1.
- **A conexão só recebe.** O laço do WebSocket só lê e põe o áudio numa fila. O
  STT lê dessa fila em outra tarefa. Assim, o `mute`, o `end` e a queda da
  conexão são vistos na hora, mesmo no modo mock, cujo STT não lê o áudio.
- **Ordem por participante (2.6).** Cada participante tem uma fila de falas com
  um único worker. A fala N+1 só é roteada depois de a N ter sido entregue. Isso
  garante a ordem, mas a tradução da N+1 espera a voz da N. Pode ser otimizado na
  Etapa 5 com processamento em paralelo e reordenação na entrega.
- **Tradução por idioma de escuta (2.5).** Os ouvintes são agrupados pelo idioma
  de escuta, e cada grupo recebe uma tradução e uma voz. Os grupos são processados
  em paralelo. Ouvintes com o mesmo idioma de quem falou não recebem nada.
- **Contexto de tradução desligado**, como no modo `conversation`. Instruções
  personalizadas e o contexto visual do PolyTalk não foram levados para as salas.
- **Silenciar fecha a frase.** Ao receber `mute`, a sessão manda ao STT ~1 s de
  silêncio antes de parar o áudio. Assim, a frase em andamento é traduzida em vez
  de ficar presa no STT.
- **Sala recém-criada conta como vazia.** O diagrama da etapa mostra a sala nascendo
  em "Aguardando". Aqui, a sala é criada pelo REST e o criador conecta logo depois.
  Até isso acontecer, ela está `empty` e expira se ninguém entrar.
- **Reconexão** (uma pessoa cair e voltar com o mesmo id) ficou para a 3.7. Hoje,
  quem volta entra como um participante novo.

### 2.2 Ciclo de vida

- Criar (`create_room`), entrar por código (sem diferenciar maiúsculas e
  minúsculas, com espaços nas pontas ignorados), sair e expirar. A limpeza roda a
  cada `ROOM_SWEEP_INTERVAL_SECONDS` (15 s) numa tarefa iniciada no `lifespan` do
  app. A sala vazia expira após `ROOM_EMPTY_TTL_SECONDS` (120 s). Se alguém voltar
  antes, ela continua.
- Limite de `ROOM_MAX_PARTICIPANTS` (8) por sala. O idioma precisa ter a forma
  `pt`, `zh` ou `pt-BR` (guardado como `pt_br`).
- Testes: `TestRoomLifecycle` em `tests/test_rooms.py` (criar, entrar, sair,
  expirar, voltar antes de expirar, código inválido, sala cheia, idioma inválido).

### 2.3 Conexão da sala

- `app/rooms/router.py`. O teste `test_two_clients_pt_zh` conecta dois clientes à
  mesma sala pelo `TestClient`, com STT, tradução e voz falsos, e confere a
  conversa inteira: entradas, avisos, traduções, `mute`, `ping` e saída.
- O `TestClient` só compartilha o laço de eventos entre as duas conexões dentro de
  `with TestClient(app)`. Fora disso, cada WebSocket ganharia um laço próprio, e
  as mensagens de um participante para o outro quebrariam.

### 2.4 Um STT por participante

- Cada conexão abre o próprio fluxo com o STT (`stream_transcribe`, política
  `pause`, como o modo `conversation`). Por padrão, a detecção é automática
  (`language=None`), porque o idioma detectado alimenta o filtro da 2.7. A tradução
  usa sempre o idioma **declarado** por quem fala, não o detectado.
- `ROOM_STT_LANGUAGE_MODE=fixed` informa o idioma ao STT. É o plano B da 1.3, para
  o caso de a detecção errar com fala real. Na prática, ele desliga o filtro.
- **Correção de uma nota da 1.3.** Lá está escrito que o modo automático faz
  "detecção restrita a pt/zh". Lendo o STT agora, vi que `candidate_languages` é
  guardado e confirmado ao cliente, mas **não é usado** na transcrição: o Whisper
  detecta livremente entre todos os idiomas. A precisão medida na 1.3 continua
  válida (foi detecção livre o tempo todo), mas o motivo descrito estava errado.
  Para o filtro, isso é bom: o Whisper pode devolver `zh` no microfone de quem
  fala português.

### 2.5 Roteamento

- `app/rooms/routing.py`. Testes em `TestRouting`: cada lado recebe só a tradução
  do outro; com dois ouvintes de chinês, há uma tradução e uma voz; quem ouve o
  idioma de quem falou não recebe nada; quem saiu no meio não recebe; falha de
  tradução vira `room_error` para o ouvinte; sala com uma pessoa só registra
  `no_listeners` e não chama o tradutor.

### 2.6 Ordem das mensagens

- `test_fast_sequence_keeps_order`: três falas seguidas, a primeira com tradução
  4× mais lenta que as outras. O ouvinte recebe `um`, `dois`, `três`, nessa ordem,
  com `sequence` 1, 2 e 3, e cada `room_translation` vem antes do seu `room_tts`.

### 2.7 Filtro de conversa cruzada

- Três modos (`ROOM_CROSSTALK_FILTER`):
  - `room` (padrão): descarta a fala detectada no idioma de fala de **outro**
    participante da sala;
  - `strict`: descarta qualquer idioma diferente do declarado;
  - `off`: não descarta nada.
- Escolhi `room` como padrão porque o Whisper às vezes classifica uma frase curta
  em português como galego ou espanhol. No modo `strict`, essas frases se perderiam.
  No `room`, só é descartado o que tem cara de ser a outra pessoa.
- Se o STT não informa o idioma, a fala passa.
- Teste unitário: `TestCrosstalkFilter`. Teste real: ver "Sala real" abaixo.

### 2.8 Avisos de entrada e saída

- Cada entrada e saída gera `participant_joined`/`participant_left` e um
  `room_state` com a lista atualizada para todos. Silenciar e reativar também
  enviam `room_state`, com o `status` da pessoa (`connected` ou `muted`).

### 2.9 Limpeza dos áudios

- A voz das salas é gravada como `media/output/room_<código>_<idioma>_<id>.wav`, e
  a sala guarda a lista dos seus arquivos. Eles são apagados quando a sala expira,
  quando passam de `ROOM_AUDIO_MAX_AGE_SECONDS` (10 min, mesmo com a sala ativa) e
  quando o app desliga.
- Conferido no container: depois dos testes reais, cada sala expirou 2 min após
  esvaziar (`room expired` no log) e os arquivos dela sumiram da pasta.
- Os arquivos `tts_*` do modo original **não** são apagados; continua como no
  PolyTalk. Na máquina de desenvolvimento, já são 676 arquivos das medições da
  Etapa 1.

### 2.10 Marcas de tempo

- Uma linha JSON por fala em `logs/room-timing.jsonl` (montado do container em
  `./logs`) e no log padrão, com o prefixo `room_timing`. Campos: marcas absolutas
  (`t`), duração do STT e, por idioma de destino, `translation_done`, `text_sent`,
  `tts_done` e `audio_sent`, contadas desde o fim da fala (`since_speech_end`). O
  `playback_started` enviado pelo celular gera uma linha separada.
- **Fim da fala no servidor.** O servidor não sabe quando a pessoa parou de falar.
  Ele estima pelo áudio recebido: guarda os trechos com voz (RMS ≥
  `STT_SILENCE_RMS_THRESHOLD`, o mesmo limiar do STT) e, quando chega a
  transcrição, pega o fim do último trecho seguido de pelo menos 75% da espera de
  silêncio. Pausas curtas no meio da frase e uma fala nova que começou antes da
  resposta do STT não confundem a estimativa (teste
  `test_speech_end_ignores_short_pauses`).
- No teste real, a diferença entre o fim estimado pelo servidor e o fim real
  (último bloco enviado pelo cliente) foi de **0,00 s** na mediana e no p95. A
  latência calculada pelo log bateu com a medida no cliente (diferença de até
  0,1 s, que é o envio pela rede local). Ressalva: a fala sintética termina de
  forma seca e o silêncio é digital. Com ruído real, a estimativa pode atrasar.

### 2.11 Modos originais

- Suíte completa: **489 passam e 4 falham**. As 4 falhas são as mesmas da linha de
  base (0.8, só no Windows). São 459 testes originais e 30 novos. As rotas
  `/api/ws/translate` (`live` e `conversation`) não foram alteradas.
- `ruff check` sem erros, e `ruff format` aplicado nos arquivos novos.

### Sala real com dois participantes

- Script: `bench/testar_sala.py`. Cria uma sala no app, conecta A (pt) e B (zh) e
  manda as 20 frases de teste alternadas, em tempo real, como dois celulares. Com
  `--cruzada 0.3`, o microfone de quem ouve também recebe a fala do outro, a
  cerca de −10 dB, como duas pessoas frente a frente. Configuração da Etapa 1. Uma
  rodada de 20 frases em cada modo.
- Resultados: `bench/resultados/2-sala-cruzada.json` e `2-sala-sem-cruzada.json`.

| | Sem conversa cruzada | Com conversa cruzada (−10 dB) |
|---|---|---|
| Frases entregues certo (1 tradução para quem ouve, nada para quem falou) | 20/20 | 20/20 |
| Traduções que voltaram para quem falou | 0 | 0 |
| Falas cruzadas descartadas pelo filtro | — | 20/20 (todas detectadas no idioma certo) |
| PT→ZH: texto / áudio, mediana (p95 do áudio), s | 1,68 / 1,81 (2,10) | 1,83 / 2,02 (2,99) |
| ZH→PT: texto / áudio, mediana (p95 do áudio), s | 1,75 / 2,59 (3,18) | 1,96 / 2,76 (3,47) |

- Sem conversa cruzada, a sala tem a mesma latência do modo `conversation` da
  Etapa 1 (1,85 / 2,45 s). A camada de salas não acrescentou atraso perceptível.
- Com conversa cruzada, a latência sobe ~0,2 s. Cada fala passa a ser transcrita
  **duas vezes**, uma em cada microfone, e as duas transcrições disputam o mesmo
  modelo na GPU (`STT_MODEL_WORKERS=1`). Mesmo assim, a mediana fica abaixo de 3 s
  nas duas direções. O p95 de ZH→PT (3,47 s) passa da meta. Fica para a Etapa 5.
- Os dois testes usam fala sintética e o mesmo computador. Com celulares, o volume
  da conversa cruzada e o ruído vão ser outros (Etapas 3 e 6).

### Etapa 2 – uso do agente

- **Executado pelo agente:**
  - leitura do modo `conversation`, do STT e do `docker-compose.yml` para o projeto;
  - o módulo `app/rooms/` e as mudanças mínimas no app e na configuração;
  - 30 testes automatizados;
  - o script da sala real, as duas medições e a conferência da limpeza no container.
- **Achados do agente:**
  - o `APP_WORKERS=3` do PolyTalk quebraria as salas em memória;
  - `candidate_languages` não é usado pelo STT, o que corrige uma nota da 1.3.
- **Erros do agente corrigidos no caminho:**
  - a primeira versão da estimativa do fim da fala contava o trecho de voz ainda
    aberto como fim de frase. O teste unitário pegou o erro;
  - um teste esperava o aviso da entrada de B e recebia antes o aviso da própria
    entrada de A.
- **Pendências humanas:**
  - revisar o PR, em especial o protocolo, que a Etapa 3 vai usar;
  - decidir se o padrão do filtro (`room`) e o tempo de expiração (120 s) servem.

## 2026-11-21 – Etapa 3 (branch `etapa-3-interface-celular`)

**Ordem trocada:** o plano previa a Etapa 4 (HTTPS) antes desta. A interface foi
feita primeiro e conferida no notebook, onde `http://127.0.0.1` já é contexto
seguro e o navegador libera o microfone. Nos celulares, pelo IP da Wi-Fi, o
microfone só funciona com HTTPS: a conferência nos aparelhos fica para depois da
Etapa 4. A página avisa isso (`room.mic_unsupported`) em vez de falhar calada.

### Projeto da interface

- Página nova `/sala` (alias `/room`), com três telas na mesma página: inicial,
  configuração e sala. `?code=K7Q29` abre direto a configuração daquela sala; é o
  link do QR code. Ao entrar, a URL vira `/sala?code=...`, e recarregar a página
  volta à configuração da mesma sala.
- Arquivos novos: `app/rooms/web.py` (rota da página, link de entrada e QR),
  `app/templates/room.html`, `app/static/js/room-app.js`,
  `app/static/css/room.css`. A tela original (`/`) só ganhou um link para a sala.
- Cores da marca PolyTalk com um sentido: laranja para falar (microfone), azul
  para ouvir (traduções).

### 3.1–3.3 Telas

- Inicial: "Criar sala" (`POST /api/rooms`) ou código (`GET /api/rooms/{code}`
  confere se existe antes de seguir). O campo aceita minúsculas e remove o que
  não é letra ou número.
- Configuração: nome, "eu falo", "quero ouvir em" (acompanha o idioma de fala até
  a pessoa mudar) e "estou de fone". A escolha fica salva no aparelho
  (`localStorage`, só por conveniência).
- Sala: código, convidar e sair no topo; lista de participantes com idioma e
  estado (conectado, silenciado, "tradução tocando" quando o áudio dessa pessoa
  está tocando); legendas com a tradução no idioma de quem segura o celular e,
  menor, o que a própria pessoa disse ("Você disse"), para ela ver se o STT
  entendeu; nível do microfone e um botão grande de silenciar embaixo, ao
  alcance do polegar.

### 3.4 Som liberado no toque

- Tudo que precisa de gesto acontece **antes do primeiro `await`** no toque em
  "Entrar": o `<audio>` único toca 0,1 s de silêncio (WAV gerado no próprio JS) e
  o `AudioContext` do microfone é criado ali. As traduções seguintes trocam só o
  `src` desse mesmo elemento, que já está liberado.
- O `AudioRecorder` do PolyTalk cria o contexto depois de pedir o microfone, ou
  seja, depois de um `await`. No Safari esse contexto pode nascer suspenso, e aí o
  microfone não manda nada. Por isso a sala usa uma subclasse
  (`RoomMicrophone extends AudioRecorder`) que recebe o contexto pronto e
  reaproveita o resto (cálculo do nível, PCM 16 kHz, cancelamento de eco).
- Se mesmo assim o navegador bloquear, a tradução volta para a frente da fila e
  aparece "Toque aqui para ligar o som".

### 3.5 Fila de reprodução

- `PlaybackQueue`: uma tradução por vez; a próxima começa no `ended` da anterior.
  Um vigia de 30 s pula um áudio que nunca termina.
- Ao começar a tocar, o celular manda `playback_started`, que o servidor já grava
  no log de tempos (Etapa 2). A Etapa 5 usa isso para medir até o som de verdade.
- **Sem fone:** o alto-falante do celular seria captado pelo próprio microfone, e
  a tradução seria traduzida de volta. Com "estou de fone" desmarcado, enquanto a
  tradução toca o celular manda silêncio no lugar do microfone. O STT fecha a
  frase pendente e não ouve o alto-falante.

### 3.6 Tela ligada

- `navigator.wakeLock.request('screen')` no toque em "Entrar". O navegador solta
  o bloqueio quando a aba some; ao voltar, a página pede de novo, retoma o
  `AudioContext` e reabre o microfone se o celular o encerrou.
- Sem suporte (iOS anterior ao 16.4, por exemplo), aparece o aviso para manter a
  tela ligada à mão.

### 3.7 Reconexão

- Se a conexão cai, o celular tenta de novo em 0,5, 1, 2, 4 e 8 s (depois a cada
  8 s), e na hora em que o sistema avisa que a rede voltou (`online`).
- Wi-Fi caído muitas vezes não fecha a conexão: ela só para de responder. O
  celular manda `ping` a cada 5 s; sem nenhuma mensagem por 15 s, descarta a
  conexão e reconecta.
- **Fantasma no servidor:** o servidor também demora a perceber a queda, e a
  pessoa ficaria duas vezes na sala. Na volta, o celular informa o id anterior
  (`rejoin`). O servidor tira o antigo antes de aceitar o novo
  (`RoomManager.drop_stale`) e avisa a sala com `participant_joined` e
  `rejoined: true`, que a interface não mostra como "entrou". A conexão antiga
  é encerrada na próxima mensagem dela.
- Se a sala expirou durante a queda (120 s vazia), a página volta à tela inicial
  com "A sala foi encerrada".
- Conferido no servidor real com um script (`websockets`): fantasma removido,
  `rejoined: true`, lista com 2 pessoas.

### 3.8 Chinês

- O PolyTalk tem 13 idiomas de interface e nenhum é chinês. Foi acrescentado
  `app/locales/zh.json` completo (134 textos, nomes de idiomas e mensagens do JS),
  então a tela original também passa a funcionar em chinês. `zh` entrou na lista
  de idiomas da interface (`app/ui_locales.py`).
- As 60 chaves `room.*` estão em PT, ZH e EN; os outros idiomas caem no inglês
  pelo mecanismo que o PolyTalk já tem. O idioma vem de `?ui_locale=`, do cookie
  ou do idioma do celular: um aparelho em chinês abre a sala em chinês.
- Os textos em chinês foram escritos pelo agente. Precisam da revisão de um
  falante.

### 3.9 QR code

- Gerado no servidor em SVG com `segno` (Python puro, nova dependência). Não usa
  internet nem biblioteca JS de terceiros.
- O link usa o endereço pelo qual quem criou a sala abriu a página (o IP do
  notebook). Se a página foi aberta por `localhost`, o QR apontaria para o próprio
  celular; para isso existe `ROOM_PUBLIC_BASE_URL`.
- O convite abre sozinho para quem criou a sala enquanto está sozinho, e fecha
  quando a segunda pessoa entra.

### 3.10 Licença

- Rodapé com "Código-fonte (AGPL-3.0)" apontando para o fork
  (`ROOM_SOURCE_URL`), "baseado no PolyTalk CE" e link para o tradutor original.

### Testes

- `tests/test_room_ui.py`: 22 testes (página e telas, código pela URL, idiomas
  nos seletores, página em chinês e pelo `Accept-Language`, catálogo `zh`
  completo, chaves `room.*` traduzidas e com os mesmos `{parâmetros}`, link da
  licença, QR, `join_url`, `rejoin` e os pontos do JS que o celular depende).
- Suíte inteira no Windows: 511 passam; as 4 falhas são as da linha de base.
- `node --check` no `room-app.js`. O comportamento no navegador (som, microfone,
  tela ligada, Wi-Fi) não tem teste automático: vai para a conferência humana.

### Etapa 3 – uso do agente

- **Executado pelo agente:** leitura do `AudioRecorder`, do i18n e das rotas do
  PolyTalk; as telas, o JS, o CSS, o catálogo em chinês, as mudanças no servidor
  (QR, `join_url`, `rejoin`) e os testes; reconstrução do container e teste da
  reconexão no servidor real.
- **Achados do agente:**
  - o `AudioRecorder` cria o `AudioContext` depois de um `await`, o que pode deixar
    o microfone mudo no Safari;
  - sem fone, a tradução tocada no alto-falante voltaria pelo microfone;
  - a queda do Wi-Fi deixaria um participante fantasma na sala.
- **Erros do agente corrigidos no caminho:**
  - um teste procurava um texto chinês da tela original no HTML, mas essa tela é
    traduzida no navegador; o teste passou a conferir o título, que vem do
    servidor;
  - o primeiro script da reconexão leu o aviso da entrada do próprio Bo no lugar
    do da Ana.
- **Sem navegador:** a extensão do Chrome continuou desconectada; nem a tela no
  notebook pôde ser vista pelo agente.
- **Pendências humanas:** a tabela "Conferência humana pendente" da
  [Etapa 3](etapas/etapa-3-interface-celular.md); revisar os textos em chinês;
  revisar o PR.
