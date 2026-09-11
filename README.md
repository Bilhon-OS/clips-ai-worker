# Worker do Arkom Clips

Serviço que o **Arkom Clips** usa para trabalhar o vídeo. Ele faz quatro coisas:

1. **baixa** o vídeo do YouTube,
2. **extrai o áudio** para a transcrição,
3. **mede o trecho** para o enquadramento automático: onde estão os rostos, quem está mexendo a
   boca e onde a câmera troca de plano (`POST /track-faces`, código em `rastreio.py`),
4. **corta o clipe** queimando a legenda estilizada no quadro.

O worker só **mede**. Quem decide quem enquadrar, quando cortar e quando encaixar o quadro inteiro é
o Arkom Clips (`supabase/functions/_shared/enquadramento.ts`, com teste).

Ele roda na **sua** conta Railway, não na nossa.

---

## 👉 Como subir o seu: [**DEPLOY.md**](DEPLOY.md)

Passo a passo, cerca de **10 minutos**. Leia esse arquivo — ele tem o que costuma dar errado e como
conferir que ficou certo.

---

## Por que na sua conta, e não na nossa

O YouTube bloqueia por **IP**. Um worker compartilhado entre todos os clientes seria bloqueado para
todos ao mesmo tempo, no mesmo instante. Rodando no seu Railway, o limite é seu — e o problema de um
cliente não vira problema dos outros.

## São DOIS serviços, não um

Esta é a parte que mais dá errado. O worker sozinho **não funciona**: sem o segundo serviço, o
download cai para **0 de 3** (medido).

| serviço | o que é | de onde vem |
|---|---|---|
| **worker** | este repositório | GitHub → *New → GitHub Repo* |
| **pot-provider** | gerador do token que o YouTube exige | imagem `brainicism/bgutil-ytdlp-pot-provider` |

O passo a passo de ligar um no outro está no [DEPLOY.md](DEPLOY.md).

## Conferir se está de pé

```bash
curl https://SEU-WORKER.up.railway.app/health
```

O `/health` **diagnostica**, não só responde "ok" — ele diz se o gerador de token está alcançável e
qual configuração está ativa:

```json
{
  "status": "ok",
  "deno": "deno 2.1.4",
  "pot_provider": "ok",
  "player_client": "android,tv_embedded,ios",
  "cookies": "ausente (normal)"
}
```

Se vier `"status": "degradado"`, o campo `problemas` diz exatamente o que fazer. Quando um download
falhar, **comece sempre pelo `/health`** — os erros que o downloader mostra quase nunca apontam a
causa real (a tradução de cada um está no [DEPLOY.md](DEPLOY.md)).

## Depois de subir

Gere o domínio público do worker no Railway (*Settings → Networking → Generate Domain*) e cole a URL
em **Configurações → Integrações** no Arkom Clips. É só isso — a partir daí o app usa o seu worker.

---

## O que tem dentro

Este repositório é um **fork do [yt-dlp](https://github.com/yt-dlp/yt-dlp)** com uma camada de
serviço em cima (`app.py`, Flask) e um `Dockerfile` que já traz tudo pronto: ffmpeg, as fontes das
legendas, o runtime de JavaScript que o YouTube exige, e o yt-dlp configurado com a combinação de
clientes que funciona hoje.

O README original do yt-dlp — o manual completo da ferramenta, em inglês — continua aqui:
[**README-yt-dlp.md**](README-yt-dlp.md). Você não precisa dele para subir o worker.

**Não altere a configuração de `player_client` sem motivo.** O padrão baixou 9 de 9 vídeos testados;
trocar para `web` derruba para 1 de 5. O porquê está no [DEPLOY.md](DEPLOY.md) § Variáveis.
