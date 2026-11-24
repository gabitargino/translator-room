# Etapa 3 – Interface web para celular

[← Etapa 2 – Salas no servidor](etapa-2-salas-servidor.md) · [Planejamento](../planejamento.md) · Próxima: [Etapa 4 – Rede e HTTPS →](etapa-4-rede-https.md)

| | |
|---|---|
| **Objetivo** | Telas para criar ou entrar numa sala, escolher os idiomas e ouvir as traduções no fone |
| **Depende de** | Etapa 2 (salas) e Etapa 4 (HTTPS, para testar no celular) |
| **Libera** | Etapa 6 (validação com dois celulares) |
| **Branch** | `etapa-3-interface-celular` (a partir da `main`, após o merge das Etapas 2 e 4) |
| **Esforço** | 7P · 3M |
| **Status** | Implementada; falta a conferência em celulares (o HTTPS da [Etapa 4](etapa-4-rede-https.md) já está pronto: ver o guia no README) |

## Subtarefas

| ID | Subtarefa | Tam. | Prioridade | Pronto quando | Status |
|---|---|---|---|---|---|
| 3.1 | Tela inicial: criar sala ou entrar por código | M | Obrigatório | Funciona em tela de celular | Implementada: `/sala`, criar ou digitar o código; testes da página |
| 3.2 | Configuração do participante: nome, idioma de fala e de escuta | P | Obrigatório | Escolhas enviadas ao entrar | Implementada: nome, fala, escuta e fone; vão na URL da conexão |
| 3.3 | Tela da sala: participantes, indicador de microfone ativo, legenda das últimas traduções, botão de silenciar | M | Obrigatório | Uso com uma mão no celular | Implementada: lista com estado, nível do microfone, legendas, botão grande de silenciar |
| 3.4 | Liberar o áudio com o toque em "Entrar" (os celulares bloqueiam som tocado sem gesto do usuário) | P | Obrigatório | A primeira tradução toca sem novo toque | Implementada: `<audio>` único liberado no toque e AudioContext criado no toque; falta conferir no iOS |
| 3.5 | Fila de reprodução: traduções tocam em sequência, sem sobreposição | P | Obrigatório | Duas traduções seguidas não se sobrepõem | Implementada: fila em `PlaybackQueue`; sem fone, o microfone manda silêncio enquanto a tradução toca |
| 3.6 | Manter a tela ligada durante a sala (o microfone para quando o celular bloqueia) | P | Importante | Conversa de 5 min sem a tela apagar | Implementada: Wake Lock, refeito ao voltar à aba; aviso se o navegador não suporta; falta a conversa de 5 min |
| 3.7 | Reconexão automática se o Wi-Fi oscilar | M | Desejável | Derrubar e restaurar a rede não exige entrar de novo | Implementada: reconexão com espera crescente, ping a cada 5 s e `rejoin` que substitui o participante antigo; testada no servidor real; falta derrubar o Wi-Fi no celular |
| 3.8 | Textos da interface em português e chinês (o PolyTalk não tem a tradução da interface para chinês) | P | Desejável | Interface completa em ZH | Implementada: `zh.json` completo (interface original também) e 60 chaves `room.*` em PT, ZH e EN |
| 3.9 | Mostrar o código da sala como QR code para o segundo celular entrar | P | Desejável | Entrar apontando a câmera | Implementada: QR code em SVG gerado no servidor (`segno`), abre sozinho para quem criou a sala |
| 3.10 | Aviso de licença AGPL com link para o código-fonte do fork | P | Importante | Link visível na interface | Implementada: link para o fork no rodapé (`ROOM_SOURCE_URL`) |

## Fluxo de telas

```mermaid
flowchart LR
    I[Tela inicial] -- Criar sala --> C[Configuração<br/>nome · fala · escuta]
    I -- Entrar com código<br/>ou QR code --> C
    C -- toque em Entrar<br/>libera som e microfone --> S[Sala]
    S -- Sair --> I
    S -. Wi-Fi caiu .-> R[Reconectando...] -. voltou .-> S
```

## Esboço da tela da sala

```text
┌──────────────────────────────┐
│  Sala  K7Q-29        [ Sair ]│
│                              │
│  ● Ana (PT)       falando... │
│  ● 李伟 (ZH)       ouvindo    │
│                              │
│  ─── últimas traduções ───   │
│  李伟: Você é de São Paulo?   │
│  李伟: A comida aqui é ótima. │
│                              │
│                              │
│      [ 🎤  Microfone ativo ] │
│      [    Silenciar        ] │
│                              │
│  Código-fonte (AGPL-3.0)     │
└──────────────────────────────┘
```

A legenda mostra a tradução **no idioma de quem está segurando o celular**. Ela
ajuda quando a voz não for entendida e serve de apoio na validação.

## Observações

- **Reaproveitamento:** o PolyTalk já tem a captura de áudio pronta
  (`app/static/js/audio-recorder.js`), com cancelamento de eco e supressão de ruído
  ligados. A interface da sala reaproveita esse módulo. A tela original continua
  existindo para os modos `live` e `conversation`.
- **Som bloqueado (3.4):** navegadores de celular, principalmente o Safari no iOS, só
  tocam áudio depois de um toque do usuário. O toque em "Entrar" precisa "liberar"
  a reprodução para as traduções seguintes tocarem sozinhas. É requisito do
  critério "sem acionar botões a cada fala".
- **Tela apagada (3.6):** com a tela bloqueada, o navegador pausa o microfone. Manter
  a tela ligada enquanto a sala está aberta.
- **Fila (3.5):** hoje o PolyTalk toca cada áudio assim que chega. Numa conversa,
  duas traduções em sequência se sobreporiam.
- **Chinês (3.8):** a interface do PolyTalk está em 14 idiomas, mas não em chinês.
  Basta acrescentar o arquivo de textos ao sistema que já existe.

## Riscos desta etapa

| Risco | Mitigação |
|---|---|
| Celular bloqueia som sem toque ou desliga o microfone com a tela apagada | 3.4 e 3.6; testar em Android e iOS |
| Fone Bluetooth com microfone ativo cai para qualidade de chamada | Testar cedo; se necessário, microfone do celular e só o áudio no fone |
| Interface pequena demais para uso com uma mão | Testar cada tela num celular real, não só no navegador do notebook |

## Resultado

- Página nova `/sala` (também `/room`), separada da tela original, que continua
  igual (ganhou só um link para a sala no rodapé).
- Arquivos novos: `app/rooms/web.py`, `app/templates/room.html`,
  `app/static/js/room-app.js`, `app/static/css/room.css`, `app/locales/zh.json`,
  `tests/test_room_ui.py` (22 testes).
- No servidor: `join_url` nas respostas de `POST/GET /api/rooms`,
  `GET /api/rooms/{code}/qr.svg` e o parâmetro `rejoin` na conexão.
- **Ordem trocada no plano:** a Etapa 3 foi feita antes da 4. No notebook
  (`http://127.0.0.1:9000/sala`) o navegador libera o microfone; nos celulares é
  preciso HTTPS. A conferência nos celulares fica para depois da Etapa 4.
- Detalhes nas [notas](../notas-implementacao.md#2026-11-21--etapa-3-branch-etapa-3-interface-celular).

## Conferência humana pendente

| O que conferir | Onde | Subtarefa |
|---|---|---|
| Telas legíveis e usáveis com uma mão | Chrome Android e Safari iOS | 3.1–3.3 |
| Primeira tradução toca sem novo toque | iOS principalmente | 3.4 |
| Duas traduções seguidas não se sobrepõem | Qualquer celular | 3.5 |
| Tela não apaga em 5 min; microfone volta depois de bloquear a tela | Android e iOS | 3.6 |
| Desligar e religar o Wi-Fi não exige entrar de novo | Qualquer celular | 3.7 |
| Textos em chinês corretos e naturais | Falante de chinês | 3.8 |
| QR code abre a sala na câmera do outro celular | Os dois celulares | 3.9 |

## Saída da etapa

- Interface funcionando em Chrome Android e Safari iOS.
- Fluxo completo: criar sala → segundo celular entra → conversa.
