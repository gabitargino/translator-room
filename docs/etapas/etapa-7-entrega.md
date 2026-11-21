# Etapa 7 – Documentação e entrega

[← Etapa 6 – Testes](etapa-6-testes.md) · [Planejamento](../planejamento.md)

| | |
|---|---|
| **Objetivo** | Deixar o projeto reproduzível por outra pessoa e o relatório completo |
| **Depende de** | Etapa 6 |
| **Libera** | Entrega da Atividade 04 |
| **Branch** | `etapa-7-entrega` (a partir da `main`, após o merge da Etapa 6) |
| **Esforço** | 3P · 2M |
| **Status** | Pendente |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 7.1 | README do fork: **o que foi adicionado, como fazer o build e como testar** (itens exigidos pelo enunciado), além de como entrar com os celulares | M | Obrigatório | Outra pessoa consegue reproduzir | Pendente |
| 7.2 | Preencher o relatório: familiaridade prévia, processo com agentes (o que funcionou, o que não funcionou, imprevistos), validação, métricas de antes e depois, aprendizados | M | Obrigatório | Nenhuma seção _(a preencher)_ | Pendente |
| 7.3 | Recontar arquivos e linhas no fim (mesmo método do apêndice do relatório) | P | Obrigatório | Tabela "antes e depois" completa | Pendente |
| 7.4 | Registrar o uso de agentes de codificação em cada etapa | P | Obrigatório | Seção 6 do relatório preenchida | Pendente |
| 7.5 | Gravar vídeo curto da demonstração com dois celulares | P | Desejável | Vídeo anexado ou com link no relatório | Pendente |

## De onde vem cada parte do relatório

```mermaid
flowchart LR
    N[notas-implementacao.md] --> R5[Relatório §5<br/>Implementação e dificuldades]
    N --> R6[Relatório §6<br/>Processo com agentes<br/>funcionou · não funcionou · imprevistos]
    N --> R10[Relatório §10<br/>Aprendizados]
    E1[Etapa 1<br/>medições] --> R5
    E5[Etapa 5<br/>tabela de latência] --> R7[Relatório §7<br/>Validação]
    E6[Etapa 6<br/>sessão e qualidade] --> R7
    C[Recontagem 7.3] --> R8[Relatório §8<br/>Antes e depois]
    P[planejamento.md<br/>fora da v1] --> R9[Relatório §9<br/>Trabalhos futuros]
```

Se as notas forem mantidas em dia durante as etapas, esta etapa é sobretudo de
organização, e não de reconstruir o que foi feito.

## Lista de conferência da entrega

Itens exigidos pelo enunciado da Atividade 04:

- [ ] Link para o fork com o código original e as partes adicionadas.
- [ ] Documentação do que foi adicionado, de como fazer o build e de como testar.
- [ ] Relatório focado no processo com agentes e na experiência com um projeto
      existente: o que funcionou, o que não funcionou, imprevistos, familiaridade
      prévia e aprendizados.
- [ ] Apresentação preparada (data a definir pelo professor).

Itens do nosso plano:

- [ ] Relatório sem nenhuma seção _(a preencher)_.
- [ ] Tabela "antes e depois" de funcionalidades e de linhas de código completa.
- [ ] Tabela de latência por direção com a definição das marcas de tempo.
- [ ] Resultado da sessão de 5 minutos e tabela de qualidade.
- [ ] Seção sobre o uso de agentes de codificação.
- [ ] README do fork com instruções de instalação e de uso com os celulares.
- [ ] Aviso de licença AGPL e link para o código-fonte na interface.
- [ ] Nenhuma chave, certificado privado ou `.env` no repositório.
- [ ] Nenhum PR, issue ou código enviado ao repositório original (regra da disciplina).
- [ ] Vídeo da demonstração (desejável).

## Observações

- **Recontagem (7.3):** usar exatamente os comandos do apêndice A do relatório,
  sobre o commit final, para os números serem comparáveis com os do commit
  `2aeadfd`.
- **Uso de agentes (7.4):** o foco da disciplina. Vale incluir exemplos concretos do
  que o agente acertou, do que precisou ser corrigido e de como o planejamento em
  etapas ajudou ou atrapalhou.

## Saída da etapa

- Repositório e relatório prontos para entrega.
