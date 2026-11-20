# Etapa 6 – Testes e validação

[← Etapa 5 – Latência](etapa-5-latencia.md) · [Planejamento](../planejamento.md) · Próxima: [Etapa 7 – Entrega →](etapa-7-entrega.md)

| | |
|---|---|
| **Objetivo** | Garantir com testes automatizados que as salas funcionam e validar a entrega com dois celulares |
| **Depende de** | Etapas 3 e 5 (validação manual); os testes automatizados 6.1–6.3 são feitos durante a Etapa 2 |
| **Libera** | Etapa 7 |
| **Branch** | `etapa-6-testes` (a partir da `main`, após o merge das Etapas 3 e 5). Os testes 6.1–6.3 são commitados na branch da Etapa 2 |
| **Esforço** | 4P · 3M |
| **Status** | Pendente |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 6.1 | Testes automatizados das salas: criar, entrar, sair, expirar, código inválido | M | Obrigatório | Passam sem modelos (modo mock) | Pendente |
| 6.2 | Testes de roteamento com dois clientes simulados em modo mock | M | Obrigatório | Cada cliente recebe só o que é dele | Pendente |
| 6.3 | Teste do filtro de conversa cruzada | P | Importante | Trecho em idioma errado é descartado | Pendente |
| 6.4 | Toda a suíte original continua passando | P | Obrigatório | Mesmo resultado da linha de base (0.8) | Pendente |
| 6.5 | Roteiro de teste manual com dois celulares (passos e o que observar) | P | Obrigatório | Roteiro nas notas | Pendente |
| 6.6 | Sessão de validação: conversa contínua de 5 min, PT ↔ ZH, com fones | M | Obrigatório | Critérios abaixo avaliados | Pendente |
| 6.7 | Avaliação qualitativa da tradução com o conjunto de frases de teste | P | Obrigatório | Tabela de frases com nota por frase | Pendente |

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

| Critério | Como observar | Resultado |
|---|---|---|
| Conversa de 5 min sem acionar botões a cada fala | Cronômetro; contar quantas vezes alguém tocou na tela | _(a preencher)_ |
| Cada um ouve só a tradução destinada a ele | Cada participante anota se ouviu algo que não era para ele | _(a preencher)_ |
| Latência mediana ≤ 3 s por direção | Tabela da Etapa 5 gerada a partir do log da sessão | _(a preencher)_ |
| Qualidade da tradução | Tabela da 6.7 | _(a preencher)_ |

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

## Riscos desta etapa

| Risco | Mitigação |
|---|---|
| Tradução com erro de sentido ou mistura de idiomas | Avaliação 6.7; ajustar o prompt; trocar de modelo se necessário |
| Falta de falante nativo de chinês para validar | Pedir ajuda cedo; declarar a limitação no relatório |
| Validação marcada perto do prazo e algo falha | Fazer um ensaio da 6.6 assim que a Etapa 3 funcionar |

## Saída da etapa

- Suíte automatizada passando (nova e original).
- Resultado da sessão de 5 min e tabela de qualidade, prontos para o relatório.
