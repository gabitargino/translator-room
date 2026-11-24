# Etapa 5 – Medição de latência

[← Etapa 4 – Rede e HTTPS](etapa-4-rede-https.md) · [Planejamento](../planejamento.md) · Próxima: [Etapa 6 – Testes →](etapa-6-testes.md)

| | |
|---|---|
| **Objetivo** | Medir mediana e p95 da latência em cada direção (PT→ZH e ZH→PT) a partir de sessões reais |
| **Depende de** | Etapa 2 (marcas de tempo, subtarefa 2.10) |
| **Libera** | Etapa 6 (critério de 3 s na validação) |
| **Branch** | `etapa-5-latencia` (a partir da `main`, após o merge da Etapa 2) |
| **Esforço** | 4P |
| **Status** | Concluída: PT→ZH 1,89 s e ZH→PT 2,79 s de mediana na sala real (clientes simulados); falta repetir com celulares na Etapa 6 |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 5.1 | Definir exatamente "fim da fala" e "início do áudio traduzido" e onde cada um é medido | P | Obrigatório | Definição escrita no relatório | Concluída: `app/rooms/latency.py` e relatório, seção 4.6 |
| 5.2 | O celular de quem ouve informa ao servidor o momento em que o áudio começou a tocar | P | Obrigatório | Evento registrado no log | Concluída: `playback_started` com `rtt_ms` e `wait_ms` |
| 5.3 | Compensar a diferença de relógio entre celular e notebook (ou medir tudo pelo relógio do servidor) | P | Obrigatório | Método documentado | Concluída: tudo no relógio do servidor, T6 = chegada do aviso − RTT/2 |
| 5.4 | Rotina que lê o log e calcula mediana e p95 por direção, exportando uma tabela | P | Obrigatório | Tabela gerada a partir de uma sessão real | Concluída: `bench/latencia_sala.py`; sala real com clientes simulados. A sessão com celulares é a 6.6 |

## Linha do tempo de uma fala

O critério da Atividade 03 é **T0 → T6**: do fim da fala ao início do áudio
traduzido. As marcas intermediárias mostram onde o tempo é gasto.

```text
 T0           T1            T2          T3          T4          T5        T6
  │            │             │           │           │           │         │
  ▼            ▼             ▼           ▼           ▼           ▼         ▼
 fim da     frase         texto      tradução     áudio      celular    áudio
 fala      fechada        pronto      pronta     sintetizado recebe    começa
 (pessoa   (silêncio      (STT)      (Ollama)    (voz)       o link    a tocar
 parou)    confirmado)                                                 no fone
  │◄─ espera ─►│◄── STT ───►│◄─ trad. ─►│◄── voz ──►│◄─ rede ──►│◄ download►│
  │  silêncio  │            │           │           │           │ e início  │
  │◄──────────────────────── latência medida (meta: mediana ≤ 3 s) ───────►│
```

| Marca | Onde é registrada | Relógio |
|---|---|---|
| T0 – fim da fala | Servidor (deduzida a partir de T1 e da espera de silêncio configurada) | Servidor |
| T1 – frase fechada | Servidor, ao receber o resultado do STT | Servidor |
| T2 – texto pronto | Servidor | Servidor |
| T3 – tradução pronta | Servidor | Servidor |
| T4 – áudio sintetizado | Servidor | Servidor |
| T5 – mensagem enviada | Servidor | Servidor |
| T6 – áudio começa a tocar | Celular de quem ouve, informado ao servidor (5.2) | Celular → precisa de compensação (5.3) |

## Observações

- **T0 é a marca mais difícil (5.1):** o servidor só sabe que a fala terminou depois
  de esperar o silêncio. A forma mais simples é T0 = T1 − espera de silêncio
  configurada. A definição escolhida precisa estar escrita no relatório, porque
  muda o número final.
- **Relógios diferentes (5.3):** o relógio do celular e o do notebook não batem.
  Duas saídas: medir a diferença no momento da conexão e compensar, ou fazer o
  celular avisar o servidor e usar a hora de chegada desse aviso (soma um pequeno
  atraso de rede, que deve ser declarado).
- **Fone Bluetooth:** acrescenta ~0,1–0,3 s entre "começa a tocar" no celular e o
  som no ouvido. Isso não é medido pelo sistema e deve ser citado como limitação.
- **Mediana e p95:** a mediana atende ao critério; o p95 mostra os piores casos
  normais, que são os que a pessoa percebe na conversa.

## Riscos desta etapa

| Risco | Mitigação |
|---|---|
| Diferença de relógio distorce T6 | 5.3, com o método declarado no relatório |
| Definição de T0 subestima a latência percebida | Explicitar a definição e a espera de silêncio no relatório |

## Saída da etapa

- Tabela de latência por direção (mediana, p95, máximo) gerada a partir do log.
- Definição das marcas escrita no relatório.

## Resultado

### Definições adotadas (5.1)

| Marca | Definição | Onde |
|---|---|---|
| T0 | Fim do último bloco de áudio com voz (RMS ≥ 0,003, o mesmo limiar do STT) recebido de quem fala antes da pausa que fechou a frase. Não usa "T1 − espera configurada": o detector de voz da sessão marca o fim real | `VoiceActivityTracker` (Etapa 2) |
| T6 | Evento `playing` do `<audio>` no celular de quem ouve | `room-app.js`, `onPlaybackStart` |
| Latência | T6 − T0, por ouvinte. A direção é `idioma de quem fala → idioma de quem ouve` | `app/rooms/latency.py` |

Conferência do T0: no teste da sala real o cliente simulado sabe o instante exato
em que mandou o último bloco com fala. O T0 do servidor ficou a 1 ms desse
instante na mediana (pior caso: 0,14 s antes, nunca depois). A definição não
esconde tempo.

### Relógios (5.2, 5.3)

Nenhuma marca usa o relógio do celular. O celular mede no próprio relógio
monotônico (`performance.now()`):

- o RTT dos `ping` (o servidor devolve no `pong` o carimbo `c` que recebeu;
  mediana dos 5 últimos);
- `wait_ms`: de receber o `room_tts` até o `playing`.

No aviso `playback_started` vão os dois valores. O servidor grava a hora de
chegada `t` e a estimativa `t_playback = t − RTT/2`. O erro possível é a assimetria
entre ida e volta, no máximo metade do RTT (2 ms no notebook; em Wi-Fi local,
tipicamente menos de 20 ms). Sem RTT válido, usa-se a chegada, e a linha registra
`"clock": "server_arrival"`. O `wait_ms` serve de conferência:
T5 + RTT/2 + `wait_ms` ≈ T6.

### Tabela (5.4)

`python bench/latencia_sala.py [--sala CÓDIGO] [--rotulo NOME]` lê
`logs/room-timing.jsonl`, junta cada fala com o aviso do ouvinte e grava
`bench/resultados/<rotulo>.json` e `.md`.

Sala real, dois clientes simulados no notebook, com conversa cruzada, 2 rodadas
das 10 frases por idioma (`bench/testar_sala.py --rotulo 5-sala-latencia
--rodadas 2`). O cliente simulado baixa o áudio assim que chega o link e avisa
`playback_started` ao terminar o download.

| Direção | Falas | Com T6 | Mediana T0→T6 (s) | p95 (s) | Máx. (s) | ≤ 3 s | Mediana T0→T5 (s) |
|---|---|---|---|---|---|---|---|
| PT→ZH | 20 | 20 | 1,89 | 2,40 | 2,41 | 20/20 | 1,88 |
| ZH→PT | 20 | 20 | 2,79 | 3,35 | 3,43 | 12/20 | 2,77 |

| Direção | Silêncio + STT | Tradução | Voz | Envio | Celular | RTT (ms) |
|---|---|---|---|---|---|---|
| PT→ZH | 1,55 | 0,24 | 0,12 | 0,00 | 0,01 | 2 |
| ZH→PT | 1,69 | 0,28 | 0,74 | 0,00 | 0,02 | 2 |

- As duas medianas atendem à meta de 3 s. O ZH→PT tem 0,9 s a mais, e a
  diferença está quase toda na voz em português (Supertonic, 0,74 s contra 0,12 s
  do Piper em chinês).
- A medida do próprio cliente (T0 real → fim do download) deu 1,87 s e 2,79 s, o
  que confere com as marcas do servidor.
- "Silêncio + STT" inclui os 0,8 s de espera de silêncio (`STT_PAUSE_FLUSH_SECONDS`).
- Ficam fora: decodificação do áudio no navegador do celular (o cliente
  simulado não decodifica), Wi-Fi real e o atraso do fone Bluetooth
  (~0,1–0,3 s, não mensurável pelo sistema). A medição com os celulares fica
  para a 6.6, com o mesmo script.
- Na primeira execução, logo depois de subir a pilha, a primeira frase não
  chegou e a segunda levou 10,7 s (modelos frios). A tabela é da segunda
  execução, com a pilha aquecida, como na sessão de validação.
