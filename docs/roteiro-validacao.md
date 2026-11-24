# Roteiro de validação com os celulares

[Planejamento](planejamento.md) · [Etapa 6](etapas/etapa-6-testes.md) · Subtarefa 6.5

Tudo o que o agente não conseguiu conferir, numa sequência só. Leva cerca de
40 min com duas pessoas. Cada parte depende da anterior: se um item falhar,
pare e veja o "Se falhar" dele.

**Material:** notebook com a pilha, dois celulares (de preferência um Android e
um iPhone), dois fones (com fio é melhor: o Bluetooth acrescenta ~0,2 s), uma
Wi-Fi em que os aparelhos se enxerguem (a da universidade costuma isolar; o
roteador do celular serve) e um cronômetro.

Marque `[x]` em cada item conferido e anote o resultado na linha
**Resultado**. Faça o commit na branch `etapa-6-testes` ou numa nova.

---

## Parte A – Notebook (5 min)

- [X] **A1.** Notebook na tomada; programas pesados fechados (o Docker de
  outros projetos também, porque disputa a memória).
- [X] **A2.** Notebook na Wi-Fi da sessão; no PowerShell, na pasta do projeto:

  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\rede-local.ps1
  docker compose up -d
  ```
- [X] **A3.** Pilha aquecida: logo depois de subir, a primeira frase pode
  levar 10 s ou se perder (modelos frios). No notebook, abra
  `http://127.0.0.1:9000/sala`, crie uma sala, fale uma frase em cada
  idioma e saia. Ou, no Git Bash:

  ```bash
  cd bench && PYTHONUTF8=1 ../.venv/Scripts/python testar_sala.py --rotulo aquecimento --so pt-01,zh-01
  ```
- [X] **A4.** IP mostrado pelo script anotado: `________________`

## Parte B – Rede e HTTPS (Etapa 4)

Escolha um dos dois caminhos. A medição oficial de latência (Parte D) foi
planejada pela Wi-Fi com o Caddy; pelo túnel o áudio passa pela internet e a
latência sobe. Anote no relatório qual caminho foi usado.

### Caminho 1 – Wi-Fi local com certificado (Caddy)

- [ ] **B1.** Abrir `http://<IP>:9080`
  - Esperado: página "translator-room – certificado".
  - Se falhar: a rede isola os aparelhos (use o roteador do celular), IP
    errado ou firewall: rode `tools\rede-local.ps1 -Firewall` **como
    administrador**.
  - Resultado – Android: ______ · iPhone: ______
- [ ] **B2.** Instalar o certificado
  ([README, passo 2](../README.md#2-instalar-o-certificado-uma-vez-em-cada-celular));
  no iPhone, ativar a confiança total.
  - Esperado: instalado sem erro.
  - Se falhar: iPhone, abrir no **Safari**; Android, procurar "certificado de
    CA" nas Configurações.
  - Resultado – Android: ______ · iPhone: ______
- [ ] **B3.** Abrir `https://<IP>:9443/sala`
  - Esperado: abre sem aviso de segurança.
  - Se falhar: certificado não instalado ou sem confiança total (iPhone).
  - Resultado – Android: ______ · iPhone: ______
- [ ] **B4.** Criar uma sala de teste e permitir o microfone.
  - Esperado: o navegador pede o microfone; o nível se mexe ao falar.
  - Se falhar: página aberta por `http://`; permissão negada antes (limpar nas
    configurações do site).
  - Resultado – Android: ______ · iPhone: ______

### Caminho 2 – Túnel da Cloudflare (sem certificado)

- [ ] **B5.** No notebook: `powershell -ExecutionPolicy Bypass -File tools\tunel-cloudflare.ps1`
  - Esperado: o script mostra `https://….trycloudflare.com/sala`.
  - Se falhar: `cloudflared` ausente (`winget install --id Cloudflare.cloudflared`)
    ou pilha fora do ar (`docker compose up -d`).
- [X] **B6.** Abrir o endereço do túnel no celular.
  - Esperado: abre sem aviso de segurança, em qualquer rede.
  - Resultado: ok em 24/11/2026 (um celular).
- [X] **B7.** Criar uma sala de teste e permitir o microfone.
  - Esperado: o navegador pede o microfone; o nível se mexe ao falar.
  - Resultado: ok em 24/11/2026; latência alta em algumas frases e
    transcrição apenas razoável.

## Parte C – Interface (Etapa 3)

Celular A cria a sala (fala **PT**, ouve **PT**); celular B entra pelo QR code
(fala **ZH**, ouve **ZH**). Os dois com fones.

- [ ] **C1.** B lê o QR code com a câmera.
  - Esperado: abre a sala certa, já com o código.
  - Resultado: ______
- [ ] **C2.** Usar as telas com uma mão.
  - Esperado: botões alcançáveis, textos legíveis, nada cortado.
  - Resultado: ______
- [ ] **C3.** A fala uma frase; B não toca em nada.
  - Esperado: a tradução toca no fone de B **sem novo toque** (no iPhone
    principalmente).
  - Resultado: ______
- [ ] **C4.** A fala duas frases seguidas, rápido.
  - Esperado: as duas tocam em B, uma depois da outra, sem sobrepor.
  - Resultado: ______
- [ ] **C5.** Deixar a sala aberta 5 min sem tocar.
  - Esperado: a tela não apaga.
  - Resultado: ______
- [ ] **C6.** Bloquear a tela de B por 10 s e desbloquear.
  - Esperado: o microfone volta sozinho (B fala e A ouve).
  - Resultado: ______
- [ ] **C7.** Desligar o Wi-Fi de B por 10 s e religar.
  - Esperado: volta para a mesma sala sem digitar o código; A vê B de novo.
  - Resultado: ______
- [ ] **C8.** Falante de chinês lê a interface em ZH.
  - Esperado: textos corretos e naturais (anote os que não estiverem).
  - Resultado: ______
- [ ] **C9.** Rodapé da página.
  - Esperado: aviso AGPL e link para o código-fonte.
  - Resultado: ______
- [ ] **C10.** Os dois celulares **saíram da sala**.

## Parte D – Sessão de validação de 5 minutos (6.6)

- [ ] **D1.** Sala **nova** criada (A em PT, B em ZH, com fones). Código:
  `________`
- [ ] **D2.** Pessoas frente a frente, a ~1 m, falando em volume normal.
  Ninguém toca na tela depois de entrar.
- [ ] **D3.** **5 min** de conversa livre cronometrados (sugestão de assunto:
  combinar uma reunião, um almoço, um preço). Frases curtas, uma pessoa de
  cada vez.
- [ ] **D4.** Durante a conversa, cada pessoa anotou:

  - frases que não chegaram ao outro;
  - traduções com sentido errado;
  - qualquer áudio que tocou no celular errado (deve ser zero);
  - travamentos ou reconexões.
- [ ] **D5.** Ao terminar, no Git Bash:

  ```bash
  PYTHONUTF8=1 .venv/Scripts/python bench/latencia_sala.py --sala <CÓDIGO> --rotulo 6-sessao-5min
  ```

  O script grava `bench/resultados/6-sessao-5min.md` com a latência por
  direção e o resumo da sessão (duração, reconexões, toques, tradução entregue
  a quem falou).
- [ ] **D6.** Caminho usado (Parte B): ☐ Wi-Fi com Caddy · ☐ túnel
- [ ] **D7.** (Opcional) Repetir trocando os celulares (rótulo
  `6-sessao-5min-b`).

Critérios (preencha com os números do script e das anotações):

- [ ] **Conversa contínua sem acionar botões** – meta ≥ 5 min.
  - Como medir: resumo da sessão, duração ≥ 5 min e "Toques em silenciar /
    reativar" = 0 / 0.
  - Resultado: ______
- [ ] **Cada um ouve só o que é para ele** – meta 0 ocorrências.
  - Como medir: resumo, "Tradução entregue a quem falou" = 0, mais as
    anotações.
  - Resultado: ______
- [ ] **Latência PT→ZH** – meta mediana ≤ 3 s.
  - Como medir: tabela do script.
  - Resultado: ______
- [ ] **Latência ZH→PT** – meta mediana ≤ 3 s.
  - Como medir: tabela do script.
  - Resultado: ______
- [ ] **Falas perdidas** – sem meta, só registrar.
  - Como medir: anotações, comparadas com "Falas transcritas" do resumo.
  - Resultado: ______

## Parte E – Qualidade da tradução (6.7)

- [ ] **E1.** Na [Etapa 6](etapas/etapa-6-testes.md#avaliação-qualitativa-67),
  coluna **Nota humana** preenchida para as 20 frases (2 = correto e
  natural, 1 = correto mas estranho, 0 = errado).
- [ ] **E2.** Quem fala chinês avaliou a coluna PT→ZH.
- [ ] **E3.** (Opcional) Frases faladas nos celulares em vez do áudio
  sintético; anotado se a transcrição mudou.

## Parte F – Depois

- [ ] **F1.** Resultados das Partes B a E preenchidos aqui e na Etapa 6.
- [ ] **F2.** Commit de `bench/resultados/6-sessao-5min.*`.
- [ ] **F3.** Relatório, seção 7: trocar "Parcial" pelos números da sessão e
  dizer o caminho usado (Wi-Fi ou túnel).
- [ ] **F4.** (Desejável, 7.5) Vídeo curto da conversa gravado.
