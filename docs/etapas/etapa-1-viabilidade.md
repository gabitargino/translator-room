# Etapa 1 – Linha de base e viabilidade

[← Etapa 0 – Preparação](etapa-0-preparacao.md) · [Planejamento](../planejamento.md) · Próxima: [Etapa 2 – Salas no servidor →](etapa-2-salas-servidor.md)

| | |
|---|---|
| **Objetivo** | Saber, **antes de construir as salas**, se a meta de 3 s é alcançável neste notebook e qual configuração usar |
| **Depende de** | Etapa 0 |
| **Libera** | Etapa 2 (só depois do portão) |
| **Branch** | `etapa-1-viabilidade` (a partir da `main`, após o merge da Etapa 0) |
| **Esforço** | 3P · 3M |
| **Status** | Em andamento desde 2026-11-21. A etapa de tradução já foi medida: 0,28–0,35 s por frase |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 1.1 | Montar um conjunto fixo de frases de teste (gravadas em PT e ZH) para todas as medições | P | Obrigatório | Conjunto salvo no repositório, ~10 frases por idioma | Concluída: [bench/](../../bench/README.md), 10 + 10 frases, áudio sintético |
| 1.2 | Medir a latência da configuração padrão no modo `conversation` (fim da fala → início do áudio) | M | Obrigatório | Mediana e p95 por direção registradas | Concluída: PT→ZH 3,46 s / 3,84 s; ZH→PT 4,38 s / 5,06 s (mediana / p95) |
| 1.3 | Avaliar a precisão do STT em chinês e português: Whisper `small` em CPU contra `medium` em GPU (se couber na VRAM com o tradutor) | M | Obrigatório | Tabela de erros e tempo por modelo; escolha registrada | Pendente |
| 1.4 | Ajustar o tempo de silêncio e o tamanho das janelas do STT para conversa; medir antes e depois | M | Obrigatório | Nova configuração com latência e qualidade registradas | Pendente |
| 1.5 | Medir duas falas simultâneas (dois fluxos de STT ao mesmo tempo) | P | Importante | Latência sob concorrência registrada | Pendente |
| 1.6 | Medir o tempo de síntese de voz em PT e ZH | P | Importante | Tempo por frase registrado | Pendente |
| **Portão** | **A mediana estimada fica abaixo de 3 s?** Se não, rever os modelos ou os parâmetros antes de seguir | — | Obrigatório | Decisão anotada nas notas | Pendente |

## Orçamento de latência (3 s)

De onde vem o tempo entre a pessoa terminar de falar e o outro começar a ouvir. Os
valores marcados como "estimado" são o que esta etapa precisa medir.

```text
fim da fala                                                 início do áudio no fone
    │                                                                   │
    ├── espera de silêncio ──┼── STT ──┼─ tradução ─┼── voz ──┼─ envio ─┤
    │   1,2 s (padrão)       │ 0,5–1,5 s│  0,3 s     │   ?     │ ~0,1 s  │
    │   meta: 0,6–0,8 s      │ estimado │  MEDIDO    │ a medir │estimado │
```

| Parte | Hoje | Fonte | Subtarefa |
|---|---|---|---|
| Espera de silêncio para fechar a frase | 1,2 s (`STT_PAUSE_FLUSH_SECONDS`) | Configuração padrão | 1.4 |
| Janela de áudio processada pelo STT | 3,0 s (`STT_STREAM_CHUNK_SECONDS`) | Configuração padrão; o guia de produção sugere 1,2 s | 1.4 |
| Reconhecimento (Whisper `small`, CPU) | 0,5–1,5 s por frase | Estimativa | 1.2, 1.3 |
| Tradução (`translategemma:4b`, GPU) | 0,28–0,35 s isolada; 0,52 s dentro do app | **Medido** em 20/11 e na 1.2 | — |
| Síntese de voz (Piper / Supertonic) | ? | A medir | 1.6 |
| Download do arquivo de áudio | 0,01–0,03 s (mesmo computador) | **Medido** na 1.2 | 1.2 |

Só a espera de silêncio padrão já consome 40% do orçamento. Por isso a 1.4 é
obrigatória.

## Portão de decisão

```mermaid
flowchart TD
    M[Medições 1.2 a 1.6] --> Q{Mediana ≤ 3 s<br/>nas duas direções?}
    Q -- sim --> OK[Seguir para a Etapa 2]
    Q -- não --> A{O que domina o tempo?}
    A -- espera de silêncio / janela --> P[Reduzir parâmetros do STT<br/>e reavaliar a qualidade]
    A -- reconhecimento --> W[Whisper na GPU<br/>ou modelo menor]
    A -- voz --> V[Trocar a voz do idioma<br/>Piper ↔ Supertonic]
    P --> M
    W --> M
    V --> M
```

## Observações

- **Conjunto de frases (1.1):** as mesmas frases servem para medir latência agora e
  para avaliar a qualidade na Etapa 6 (6.7). Gravar, e não falar ao vivo, deixa as
  medições comparáveis entre configurações.
- **VRAM (1.3):** o tradutor ocupa 2,9 GB dos 6 GB. O Whisper `medium` na GPU
  provavelmente cabe junto, mas é preciso confirmar com os dois carregados.
- **Idioma do STT (1.3):** com Whisper, detectar o idioma em frases curtas é pouco
  confiável. Numa sala, cada participante declara o idioma em que fala, então dá
  para fixar o idioma e evitar o erro. A desvantagem é perder o sinal usado no
  filtro de conversa cruzada (2.7). A decisão sai desta medição.
- **Concorrência (1.5):** o STT do PolyTalk tem 2 workers por padrão, e o Ollama
  processa pedidos em fila. Duas falas simultâneas devem funcionar, mas a segunda
  pode esperar a primeira.

## Riscos desta etapa

| Risco | Mitigação |
|---|---|
| Latência acima de 3 s por causa do STT em CPU e da espera por silêncio | Portão de decisão; ajustar parâmetros; Whisper na GPU |
| Whisper `small` erra muito em chinês | Comparar com `medium`; fixar o idioma por participante |
| Reduzir a espera de silêncio corta frases no meio | Medir qualidade junto com latência na 1.4 |

## Saída da etapa

- Configuração do STT escolhida e justificada.
- Tabela de latência por parte e por direção.
- Decisão do portão registrada nas notas.
