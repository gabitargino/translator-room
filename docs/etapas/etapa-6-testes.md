# Etapa 6 – Testes e validação

[← Etapa 5 – Latência](etapa-5-latencia.md) · [Planejamento](../planejamento.md) · Próxima: [Etapa 7 – Entrega →](etapa-7-entrega.md)

| | |
|---|---|
| **Objetivo** | Garantir com testes automatizados que as salas funcionam e validar a entrega com dois celulares |
| **Depende de** | Etapas 3 e 5 (validação manual); os testes automatizados 6.1–6.3 são feitos durante a Etapa 2 |
| **Libera** | Etapa 7 |
| **Branch** | `etapa-6-testes` (a partir da `main`, após o merge das Etapas 3 e 5). Os testes 6.1–6.3 são commitados na branch da Etapa 2 |
| **Esforço** | 4P · 3M |
| **Status** | Implementada: suíte, roteiro, ensaio de 5 min na pilha real e avaliação preliminar; falta a sessão com celulares e a nota humana |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 6.1 | Testes automatizados das salas: criar, entrar, sair, expirar, código inválido | M | Obrigatório | Passam sem modelos (modo mock) | Concluída na Etapa 2: TestRoomLifecycle, TestAudioCleanup |
| 6.2 | Testes de roteamento com dois clientes simulados em modo mock | M | Obrigatório | Cada cliente recebe só o que é dele | Concluída na Etapa 2: TestRouting, TestRoomWebSocket (dois clientes) |
| 6.3 | Teste do filtro de conversa cruzada | P | Importante | Trecho em idioma errado é descartado | Concluída na Etapa 2: TestCrosstalkFilter |
| 6.4 | Toda a suíte original continua passando | P | Obrigatório | Mesmo resultado da linha de base (0.8) | Concluída: 4 falhas, as mesmas da linha de base (só Windows); tudo o mais passa |
| 6.5 | Roteiro de teste manual com dois celulares (passos e o que observar) | P | Obrigatório | Roteiro nas notas | Concluída: [roteiro-validacao.md](../roteiro-validacao.md), com as conferências pendentes das Etapas 3 e 4 |
| 6.6 | Sessão de validação: conversa contínua de 5 min, PT ↔ ZH, com fones | M | Obrigatório | Critérios abaixo avaliados | Ensaio com clientes simulados aprovado (abaixo); falta a sessão com celulares ([roteiro](../roteiro-validacao.md), Parte D) |
| 6.7 | Avaliação qualitativa da tradução com o conjunto de frases de teste | P | Obrigatório | Tabela de frases com nota por frase | Preliminar: nota do agente (PT→ZH 17/20, ZH→PT 15/20); falta a nota humana |

## Níveis de teste

```text
                    ┌─────────────────────────┐
                    │  Validação manual (6.6) │  2 celulares, 5 min, fones
                    │  + qualidade (6.7)      │  → critérios da Atividade 03
                ┌───┴─────────────────────────┴───┐
                │  Integração em modo mock (6.2)  │  2 clientes simulados numa sala
                │                                 │  → roteamento e ordem
            ┌───┴─────────────────────────────────┴───┐
            │  Unidade (6.1, 6.3) + suíte original (6.4) │  regras da sala, filtro
            │                                            │  → rápidos, rodam sempre
            └────────────────────────────────────────────┘
```

A base roda em segundos e sem modelos, graças ao modo mock do PolyTalk. Isso permite
rodar os testes a cada mudança. O topo depende de pessoas e celulares e roda poucas
vezes.

## Critérios avaliados na sessão de validação (6.6)

| Critério | Como observar | Ensaio (clientes simulados) | Sessão com celulares |
|---|---|---|---|
| Conversa de 5 min sem acionar botões a cada fala | Resumo da sessão (`bench/latencia_sala.py`): duração, toques em silenciar/reativar, reconexões | 6 min 43 s, 0 toques, 0 reconexões, 60/60 falas entregues | Pendente |
| Cada um ouve só a tradução destinada a ele | Resumo: "Tradução entregue a quem falou"; anotações dos participantes | 0 vazamentos; 60/60 falas captadas pelo outro microfone descartadas | Pendente |
| Latência mediana ≤ 3 s por direção | Tabela da Etapa 5 gerada a partir do log da sessão | PT→ZH 1,83 s (p95 2,20); ZH→PT 2,52 s (p95 3,10) | Pendente |
| Qualidade da tradução | Tabela da 6.7 | Nota do agente: PT→ZH 17/20, ZH→PT 15/20 | Nota humana pendente |

### Ensaio da 6.6

Mitigação prevista nos riscos ("fazer um ensaio da 6.6"). Pilha real no notebook,
dois clientes simulados que se comportam como os celulares (ping, download,
aviso de reprodução) e conversa cruzada: o microfone de quem ouve capta a fala do
outro a −10 dB. Três rodadas das 20 frases, sem pausa
(`bench/testar_sala.py --rotulo 6-ensaio-5min --rodadas 3`, sala `ZNYFE`).

| Direção | Falas | Mediana T0→T6 | p95 | Máx. | ≤ 3 s |
|---|---|---|---|---|---|
| PT→ZH | 30 | 1,83 s | 2,20 s | 2,33 s | 30/30 |
| ZH→PT | 30 | 2,52 s | 3,10 s | 3,27 s | 28/30 |

Resultados em `bench/resultados/6-ensaio-5min*.{json,md}`. O que o ensaio não
cobre: microfone e alto-falante de verdade, ruído do ambiente, Wi-Fi, navegador
do celular e tela apagando. É o que a sessão com celulares precisa mostrar.

## Esboço do roteiro manual (6.5)

1. Notebook ligado na tomada, programas desnecessários fechados, pilha no ar.
2. Os dois celulares na mesma Wi-Fi do notebook, com fones conectados.
3. Celular A cria a sala (fala PT, ouve PT); celular B entra pelo código ou QR code
   (fala ZH, ouve ZH).
4. Conferir: os dois aparecem na sala; o indicador de microfone está ativo.
5. Conversa livre de 5 minutos, cronometrada, com as pessoas frente a frente.
6. Durante a conversa, anotar: falas perdidas, traduções erradas, áudio que tocou
   no celular errado, travamentos.
7. Ao final, exportar o log e gerar a tabela de latência.
8. Repetir com as pessoas trocando de papel, se possível.

## Avaliação qualitativa (6.7)

Usar o mesmo conjunto de frases da Etapa 1 (1.1). Para cada frase, uma nota simples:

| Nota | Significado |
|---|---|
| 2 | Sentido correto e natural |
| 1 | Sentido correto, mas estranho ou com detalhes perdidos |
| 0 | Sentido errado ou incompreensível |

Idealmente a nota em chinês é dada por alguém fluente. Se não houver, registrar
essa limitação no relatório.

### Resultado preliminar (avaliação do agente)

Tradução de ponta a ponta na sala real (áudio sintético → STT → tradução), sala
`2R5K5` da Etapa 5, `bench/resultados/5-sala-latencia.json`. As duas rodadas
deram textos idênticos. A nota do agente é preliminar; a **nota humana** vale
para o relatório e é preenchida na [Parte E do roteiro](../roteiro-validacao.md#parte-e--qualidade-da-tradução-67).

**PT → ZH**

| ID | Fala | Tradução do sistema | Nota do agente | Motivo | Nota humana |
|---|---|---|---|---|---|
| pt-01 | Bom dia, obrigado por virem à reunião de hoje. | 早上好，感谢大家参加今天的会议。 | 2 | | |
| pt-02 | Vocês conseguem me ouvir bem? | 您能听清楚我吗？ | 1 | "Vocês" virou 您 (singular); falta 说话 | |
| pt-03 | Podemos começar pela apresentação do novo produto. | 我们可以先介绍一下新产品。 | 2 | | |
| pt-04 | O preço por unidade é de doze reais e cinquenta centavos. | 单价为 12.50 巴西雷亚尔。 | 2 | O STT escreveu "R$ 12,50"; valor certo | |
| pt-05 | Precisamos entregar a primeira remessa até o dia quinze de março. | 我们需要在3月15日之前交付第一批货物。 | 2 | | |
| pt-06 | Você pode repetir mais devagar, por favor? | 请您再说一遍，慢一点。 | 2 | | |
| pt-07 | Onde fica a estação de metrô mais próxima? | 最近的地铁站距离我有多远？ | 1 | Pergunta "onde" virou "a que distância" | |
| pt-08 | Eu concordo com a proposta, mas o prazo está muito curto. | 我赞同这个方案，但时间安排太紧凑了。 | 2 | | |
| pt-09 | Vamos almoçar juntos depois da reunião? | 我们会在会议结束后一起吃午饭。 | 1 | O STT perdeu o "?"; o convite virou afirmação | |
| pt-10 | Muito obrigado, foi um prazer conhecer vocês. | 非常感谢，很高兴认识你们。 | 2 | Igual à referência | |

**ZH → PT**

| ID | Fala | Tradução do sistema | Nota do agente | Motivo | Nota humana |
|---|---|---|---|---|---|
| zh-01 | 你好，很高兴认识你。 | Olá, é um prazer conhecer-te. | 1 | Português de Portugal ("conhecer-te") | |
| zh-02 | 请问洗手间在哪里？ | Onde é que fica o banheiro? | 2 | | |
| zh-03 | 这个价格有点贵，能便宜一点吗？ | Será que este preço poderia ser um pouco mais baixo? | 1 | O STT trocou 贵 por 归; perdeu "está caro" | |
| zh-04 | 我们公司在上海，有两百多名员工。 | Nossa empresa tem mais de 200 funcionários em Xangai. | 2 | | |
| zh-05 | 下个星期三下午三点可以开会吗？ | Seria possível marcar uma reunião para a próxima semana, por volta das 15h? | 1 | O STT trocou 三 por 散; perdeu "quarta-feira" | |
| zh-06 | 对不起，我没听懂，请再说一遍。 | Desculpe, não entendi. Poderia repetir, por favor? | 2 | | |
| zh-07 | 我们需要先看一下合同的细节。 | Precisamos primeiro analisar os detalhes do contrato. | 2 | | |
| zh-08 | 样品已经寄出了，大概五天能到。 | A amostra já foi enviada e deve chegar em cerca de cinco dias. | 2 | | |
| zh-09 | 你喜欢吃中国菜吗？ | Você gosta de comer comida chinesa? | 1 | "Comer comida" redundante | |
| zh-10 | 谢谢你的帮助，我们保持联系。 | Obrigado pela sua ajuda, mantemos contacto. | 1 | Português de Portugal ("contacto"); "mantemos" em vez de "vamos manter" | |

| Direção | Nota 2 | Nota 1 | Nota 0 | Total (máx. 20) |
|---|---|---|---|---|
| PT→ZH | 7 | 3 | 0 | 17 |
| ZH→PT | 5 | 5 | 0 | 15 |

- Nenhuma tradução com sentido errado. Das 8 notas 1, três vêm do STT (sinal de
  pergunta perdido, 贵→归, 三→散), e não da tradução.
- O `translategemma:4b` às vezes traduz para o português de Portugal
  ("contacto", "conhecer-te"). Foi testada uma instrução pedindo pt-BR pelo
  `custom_instruction` do PolyTalk, sem mexer no código original: as 10
  traduções ZH→PT ficaram praticamente iguais ("contacto" continuou) e a mediana
  subiu de 0,340 s para 0,356 s. Descartada; trocar de modelo fica como trabalho
  futuro.
- No mesmo teste, só com a tradução (texto chinês correto, sem STT), zh-05 saiu
  "próxima **terça-feira**" para 星期三 (quarta-feira): erro de sentido do
  próprio modelo de tradução. Na sala, o erro do STT (三→散) fez o dia sumir em
  vez de sair errado. Datas e números merecem atenção na avaliação humana.
- O Whisper `small` ainda escreve parte do chinês em caracteres tradicionais
  (`很高興`); a tradução não é afetada.

## Riscos desta etapa

| Risco | Mitigação |
|---|---|
| Tradução com erro de sentido ou mistura de idiomas | Avaliação 6.7; ajustar o prompt; trocar de modelo se necessário |
| Falta de falante nativo de chinês para validar | Pedir ajuda cedo; declarar a limitação no relatório |
| Validação marcada perto do prazo e algo falha | Fazer um ensaio da 6.6 assim que a Etapa 3 funcionar |

## Saída da etapa

- Suíte automatizada passando (nova e original).
- Resultado da sessão de 5 min e tabela de qualidade, prontos para o relatório.
