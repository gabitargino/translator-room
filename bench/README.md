# Conjunto de medição (Etapas 1 e 2)

Frases fixas em PT e ZH usadas em todas as medições de latência e de precisão. Com o
mesmo áudio, os resultados de configurações diferentes ficam comparáveis. Plano:
[docs/etapas/etapa-1-viabilidade.md](../docs/etapas/etapa-1-viabilidade.md).

| Arquivo | Conteúdo |
|---|---|
| `frases.tsv` | `id`, `idioma`, `texto` (o que é falado) e `referencia` (tradução esperada, para a avaliação da 6.7) |
| `audio/<id>.wav` | Uma frase por arquivo: 16 kHz, mono, 16 bits, sem silêncio nas pontas |
| `gerar_audios.py` | Gera os áudios com as vozes da própria pilha |
| `comum.py` | Funções compartilhadas (leitura, reamostragem, percentis). Só usa a biblioteca padrão |
| `medir_conversa.py` | Latência de ponta a ponta no modo conversation, por parte (1.2, 1.4) |
| `medir_stt.py` | Precisão e tempo do STT, idioma fixo ou automático (1.3) |
| `medir_concorrencia.py` | Duas sessões falando ao mesmo tempo (1.5) |
| `medir_tts.py` | Tempo de síntese das vozes; passos do Supertonic (1.6) |
| `inteligibilidade_tts.py` | Transcreve a voz gerada para estimar se é inteligível (1.6) |
| `testar_sala.py` | Sala real com dois participantes simulados: roteamento, conversa cruzada e latência (Etapa 2) |
| `resultados/` | Resultados brutos (JSON) de cada medição citada nas notas |

## Frases

São 10 por idioma, num cenário de reunião de negócios e de viagem. Há frases curtas
(1,3 s) e longas (4,1 s), números, datas, preço e nome de cidade, que são os pontos
onde o STT e a tradução costumam errar.

## Como os áudios foram feitos

Foram **sintetizados**, não gravados por pessoas:

- **PT:** Supertonic (`:7788`), alternando as vozes F1–F5 e M1–M5, 8 passos.
- **ZH:** Piper (`:5000`), voz `zh_CN-huayan-medium`, a única voz chinesa instalada.

Cada áudio é convertido para 16 kHz (sinc janelado com filtro anti-aliasing) e tem o
silêncio das pontas removido. Assim, o fim do arquivo é o fim da fala, o ponto de
partida da medição de latência.

```bash
docker compose up -d tts supertonic-tts
python bench/gerar_audios.py              # mantém os arquivos que já existem
python bench/gerar_audios.py --sobrescrever
```

### Limitação

Fala sintética é mais limpa e regular que a fala real: sem ruído, sotaque ou
hesitação. Por isso, a precisão medida com ela é um **teto otimista**. A latência
não muda tanto, porque depende da duração do áudio e da configuração do STT.

Para trocar por gravações reais, grave com o mesmo `id` (16 kHz, mono, WAV 16 bits,
com pouco silêncio no início e no fim) e substitua o arquivo em `audio/`. O gerador
não sobrescreve arquivos existentes sem `--sobrescrever`. Registre a troca nas notas
de implementação.

## Como medir

Com a pilha de pé (`docker compose up -d`) e o modo real ligado em
`config/config.yaml`:

```bash
.venv/Scripts/python -m pip install websockets opencc-python-reimplemented
PYTHONUTF8=1 .venv/Scripts/python bench/medir_conversa.py --rotulo teste --rodadas 1
```

Cada script explica as opções com `--help`. Os resultados e as conclusões de cada
medição estão em [docs/notas-implementacao.md](../docs/notas-implementacao.md),
entrada "Etapa 1".
