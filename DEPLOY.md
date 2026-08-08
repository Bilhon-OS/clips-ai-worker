# Deploy na sua Railway — 10 minutos

Este worker faz três coisas para o Arkom Clips: **baixa** o vídeo do YouTube, **extrai o áudio** e
**corta o clipe queimando a legenda no quadro**. Ele roda na **sua** conta Railway, com o seu IP.

> **Por que na sua conta:** o YouTube bloqueia por IP. Um worker compartilhado entre clientes seria
> bloqueado para todos ao mesmo tempo. Rodando no seu, o limite é seu.

---

## São DOIS serviços, não um

Esta é a parte que costuma dar errado. O worker sozinho **não funciona** — medido: sem o segundo
serviço, o download cai para **0 de 3**.

| serviço | o que é | de onde vem |
|---|---|---|
| **1. worker** | este repositório | GitHub (fork/deploy from repo) |
| **2. pot-provider** | gerador de PO token do YouTube | imagem `brainicism/bgutil-ytdlp-pot-provider` |

O YouTube exige um *proof-of-origin token* para servir vídeo a IP de datacenter. O segundo serviço
gera esse token; o worker o consome.

---

## Passo a passo

**1. Crie o `pot-provider`**
No seu projeto Railway: *New → Docker Image* → `brainicism/bgutil-ytdlp-pot-provider`.
Anote **o nome exato** que o Railway deu ao serviço (ex.: `bgutil-pot-provider`). Você vai precisar.

**2. Crie o `worker`**
*New → GitHub Repo* → este repositório. O `Dockerfile` cuida do resto (ffmpeg, fontes, yt-dlp, Deno).

**3. Ligue um no outro** — Variables do **worker**:

```
BGUTIL_POT_BASE_URL = http://<NOME-EXATO-DO-SERVICO-1>.railway.internal:4416
```

⚠️ **O nome tem que bater com o do passo 1.** Se você chamou o serviço de `pot`, a URL é
`http://pot.railway.internal:4416`. Errar aqui não dá erro de configuração — dá
*"Sign in to confirm you're not a bot"* na hora de baixar, e você vai procurar no lugar errado.

**4. Gere o domínio público do worker** (Settings → Networking → Generate Domain) e cole a URL em
**Configurações → Integrações** no Arkom Clips.

---

## Confira antes de usar

```bash
curl https://SEU-WORKER.up.railway.app/health
```

O `/health` **diagnostica**, não só responde "ok":

```json
{
  "status": "ok",
  "deno": "deno 2.1.4",
  "pot_provider": "ok",
  "pot_provider_url": "http://bgutil-pot-provider.railway.internal:4416",
  "player_client": "android,tv_embedded,ios",
  "cookies": "ausente (normal)"
}
```

Se vier `"status": "degradado"`, o campo `problemas` diz exatamente o que fazer. Os três casos:

| o que aparece | causa | conserto |
|---|---|---|
| `deno: AUSENTE` | imagem antiga | rebuild sem cache |
| `pot_provider: INALCANÇÁVEL` | nome errado na URL | corrija o `BGUTIL_POT_BASE_URL` (passo 3) |
| `player_client` começa com `web` | alguém sobrescreveu | remova o `YTDLP_PLAYER_CLIENT` |

---

## Variáveis

| variável | precisa? | padrão |
|---|---|---|
| `BGUTIL_POT_BASE_URL` | **sim**, se o serviço 1 não se chamar `bgutil-pot-provider` | `http://bgutil-pot-provider.railway.internal:4416` |
| `YTDLP_PLAYER_CLIENT` | não | `android,tv_embedded,ios` |
| `YTDLP_COOKIES_BASE64` | não | — |

**Não mexa no `YTDLP_PLAYER_CLIENT` sem motivo.** O padrão baixou **9 de 9** vídeos testados em
2026-08-08. Trocar para `web` derruba para 1 de 5 (é o client que o YouTube mais vigia), e `tv`
sozinho faz o yt-dlp reportar *"This video is DRM protected"* até em vídeo sem DRM nenhum.

O `YTDLP_COOKIES_BASE64` é a última linha, não a primeira: cookies expiram e exigem uma conta
descartável por cliente. Com o POT provider e a cadeia de clients acima, **não é preciso**.

---

## Quando algo falha

O erro que o yt-dlp mostra quase nunca aponta a causa. Tradução:

| erro | o que realmente é |
|---|---|
| `n challenge solving failed` | falta Deno (ou está usando Node, que é v18 — o EJS exige ≥22) |
| `Sign in to confirm you're not a bot` | POT provider fora do ar, ou `player_client` errado |
| `This video is DRM protected` | client de TV recebendo faixas com DRM — **não** é o vídeo |
| `Requested format is not available` | nenhum client resolveu formatos; veja os dois de cima |

Comece sempre pelo `/health`.

---

## 🔴 O bloqueio do YouTube é CUMULATIVO — leia antes de colocar em produção

Medido em 2026-08-08, no mesmo worker e na mesma hora, à medida que o número de downloads subia:

```
9 de 9  →  intermitente  →  0 de 5
```

Não é aleatório. O YouTube conta downloads **por IP** e vai fechando. Client, PO token, formato
progressivo e retry **ampliam a janela**, mas nenhum muda o IP — e é o IP que ele conta. Um worker
de uso real é bloqueado em horas.

### A solução: proxy residencial

```
YTDLP_PROXY = http://usuario:senha@host:porta
```

Com isso cada requisição sai de um IP doméstico diferente e o contador nunca acumula. Custa entre
**US$ 10 e 30/mês** em provedores de proxy residencial rotativo. É a única variável que ataca a
causa; todo o resto é paliativo.

Sem `YTDLP_PROXY`, o worker sobe e loga um aviso — e o `/health` continua `ok`, porque o problema
não é de configuração: é de volume. Espere falhas de *"not a bot"* conforme o uso cresce.
