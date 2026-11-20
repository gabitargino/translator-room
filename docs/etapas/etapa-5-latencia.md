# Etapa 5 – Medição de latência

[← Etapa 4 – Rede e HTTPS](etapa-4-rede-https.md) · [Planejamento](../planejamento.md) · Próxima: [Etapa 6 – Testes →](etapa-6-testes.md)

| | |
|---|---|
| **Objetivo** | Medir mediana e p95 da latência em cada direção (PT→ZH e ZH→PT) a partir de sessões reais |
| **Depende de** | Etapa 2 (marcas de tempo, subtarefa 2.10) |
| **Libera** | Etapa 6 (critério de 3 s na validação) |
| **Branch** | `etapa-5-latencia` (a partir da `main`, após o merge da Etapa 2) |
| **Esforço** | 4P |
| **Status** | Pendente |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 5.1 | Definir exatamente "fim da fala" e "início do áudio traduzido" e onde cada um é medido | P | Obrigatório | Definição escrita no relatório | Pendente |
| 5.2 | O celular de quem ouve informa ao servidor o momento em que o áudio começou a tocar | P | Obrigatório | Evento registrado no log | Pendente |
| 5.3 | Compensar a diferença de relógio entre celular e notebook (ou medir tudo pelo relógio do servidor) | P | Obrigatório | Método documentado | Pendente |
| 5.4 | Rotina que lê o log e calcula mediana e p95 por direção, exportando uma tabela | P | Obrigatório | Tabela gerada a partir de uma sessão real | Pendente |

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
