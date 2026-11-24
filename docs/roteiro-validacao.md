# Roteiro de validação com os celulares

[Planejamento](planejamento.md) · [Etapa 6](etapas/etapa-6-testes.md) · Subtarefa 6.5

Tudo o que o agente não conseguiu conferir, numa sequência só. Leva cerca de
40 min com duas pessoas. Cada parte depende da anterior: se uma falhar, pare e
veja a coluna "Se falhar".

**Material:** notebook com a pilha, dois celulares (de preferência um Android e
um iPhone), dois fones (com fio é melhor: o Bluetooth acrescenta ~0,2 s), uma
Wi-Fi em que os aparelhos se enxerguem (a da universidade costuma isolar; o
roteador do celular serve) e um cronômetro.

Anote os resultados direto nas tabelas (coluna **Resultado**) e faça o commit
na branch `etapa-6-testes` ou numa nova.

---

## Parte A – Notebook (5 min)

1. Notebook na tomada; feche programas pesados (o Docker de outros projetos
   também, porque disputa a memória).
2. Conecte o notebook à Wi-Fi da sessão e rode, no PowerShell, na pasta do
   projeto:

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\rede-local.ps1
   docker compose up -d
   ```

3. Aqueça a pilha: logo depois de subir, a primeira frase pode levar 10 s ou se
   perder (modelos frios). No notebook, abra `http://127.0.0.1:9000/sala`, crie
   uma sala, fale uma frase em cada idioma e saia. Ou, no Git Bash:

   ```bash
   cd bench && PYTHONUTF8=1 ../.venv/Scripts/python testar_sala.py --rotulo aquecimento --so pt-01,zh-01
   ```

4. Anote o IP mostrado pelo script: ______________

## Parte B – Rede e certificado (Etapa 4)

| # | O que fazer | Esperado | Se falhar | Resultado Android | Resultado iPhone |
|---|---|---|---|---|---|
| B1 | Abrir `http://<IP>:9080` | Página "translator-room – certificado" | Rede isola os aparelhos (use o roteador do celular), IP errado ou firewall: rode `tools\rede-local.ps1 -Firewall` **como administrador** | | |
| B2 | Instalar o certificado ([README, passo 2](../README.md#2-instalar-o-certificado-uma-vez-em-cada-celular)); no iPhone, ativar a confiança total | Instalado sem erro | iPhone: abrir no **Safari**; Android: procurar "certificado de CA" nas Configurações | | |
| B3 | Abrir `https://<IP>:9443/sala` | Abre sem aviso de segurança | Certificado não instalado ou sem confiança total (iPhone) | | |
| B4 | Criar uma sala de teste e permitir o microfone | O navegador pede o microfone; o nível se mexe ao falar | Página aberta por `http://`; permissão negada antes (limpar nas configurações do site) | | |

## Parte C – Interface (Etapa 3)

Celular A cria a sala (fala **PT**, ouve **PT**); celular B entra pelo QR code
(fala **ZH**, ouve **ZH**). Os dois com fones.

| # | O que fazer | Esperado | Resultado |
|---|---|---|---|
| C1 | B lê o QR code com a câmera | Abre a sala certa, já com o código | |
| C2 | Usar as telas com uma mão | Botões alcançáveis, textos legíveis, nada cortado | |
| C3 | A fala uma frase; B não toca em nada | A tradução toca no fone de B **sem novo toque** (no iPhone principalmente) | |
| C4 | A fala duas frases seguidas, rápido | As duas tocam em B, uma depois da outra, sem sobrepor | |
| C5 | Deixar a sala aberta 5 min sem tocar | A tela não apaga | |
| C6 | Bloquear a tela de B por 10 s e desbloquear | O microfone volta sozinho (B fala e A ouve) | |
| C7 | Desligar o Wi-Fi de B por 10 s e religar | Volta para a mesma sala sem digitar o código; A vê B de novo | |
| C8 | Falante de chinês lê a interface em ZH | Textos corretos e naturais (anote os que não estiverem) | |
| C9 | Rodapé da página | Aviso AGPL e link para o código-fonte | |

Depois da Parte C, **saiam da sala** nos dois celulares.

## Parte D – Sessão de validação de 5 minutos (6.6)

1. Crie uma **sala nova** (A em PT, B em ZH, com fones) e anote o código:
   ______
2. Pessoas frente a frente, a ~1 m, falando em volume normal. Ninguém toca na
   tela depois de entrar.
3. Cronometre **5 min** de conversa livre (sugestão de assunto: combinar uma
   reunião, um almoço, um preço). Frases curtas, uma pessoa de cada vez.
4. Cada pessoa anota durante a conversa:
   - frases que não chegaram ao outro;
   - traduções com sentido errado;
   - qualquer áudio que tocou no celular errado (deve ser zero);
   - travamentos ou reconexões.
5. Ao terminar, no Git Bash:

   ```bash
   PYTHONUTF8=1 .venv/Scripts/python bench/latencia_sala.py --sala <CÓDIGO> --rotulo 6-sessao-5min
   ```

   O script grava `bench/resultados/6-sessao-5min.md` com a latência por direção
   e o resumo da sessão (duração, reconexões, toques, tradução entregue a quem
   falou).
6. Se possível, repitam trocando os celulares (rótulo `6-sessao-5min-b`).

| Critério | Meta | Como medir | Resultado |
|---|---|---|---|
| Conversa contínua sem acionar botões | ≥ 5 min | Resumo da sessão: duração ≥ 5 min e "Toques em silenciar / reativar" = 0 / 0 | |
| Cada um ouve só o que é para ele | 0 ocorrências | Resumo: "Tradução entregue a quem falou" = 0, mais as anotações | |
| Latência PT→ZH | mediana ≤ 3 s | Tabela do script | |
| Latência ZH→PT | mediana ≤ 3 s | Tabela do script | |
| Falas perdidas | — | Anotações (comparar com "Falas transcritas" do resumo) | |

## Parte E – Qualidade da tradução (6.7)

Na [Etapa 6](etapas/etapa-6-testes.md#avaliação-qualitativa-67) está a tabela
com as 20 frases de teste, a tradução que o sistema produziu e a nota preliminar
do agente. Preencham a coluna **Nota humana** (2 = correto e natural, 1 =
correto mas estranho, 0 = errado). Quem fala chinês avalia a coluna PT→ZH.

Opcional: falar as frases nos celulares em vez de usar o áudio sintético, e
anotar se a transcrição mudou.

## Parte F – Depois

- [ ] Resultados das Partes B a E preenchidos aqui e na Etapa 6.
- [ ] Commit de `bench/resultados/6-sessao-5min.*`.
- [ ] Relatório, seção 7: trocar "Parcial" pelos números da sessão.
- [ ] Gravar um vídeo curto da conversa (7.5, desejável).
