# Playlist Migration API

Backend API para migrar playlists a partir de arquivos `.txt` para plataformas de streaming. Suporta **Spotify** e **YouTube Music**, com arquitetura extensivel para futuras plataformas.

> **Status:** E2E validado com sucesso em ambas as plataformas — 209 testes unitarios + testes reais com playlist de 19 faixas (Spotify: 94.7% match rate | YouTube Music: 100% match rate).

---

## Indice

- [Visao Geral](#visao-geral)
- [Arquitetura](#arquitetura)
- [Tech Stack](#tech-stack)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Instalacao e Setup](#instalacao-e-setup)
- [Configuracao](#configuracao)
- [Endpoints da API](#endpoints-da-api)
- [Formato do Arquivo .txt](#formato-do-arquivo-txt)
- [Pipeline de Processamento](#pipeline-de-processamento)
- [Padroes de Resiliencia](#padroes-de-resiliencia)
- [Fuzzy Matching](#fuzzy-matching)
- [Search Cache (Redis)](#search-cache-redis)
- [Seguranca](#seguranca)
- [Testes](#testes)
- [Configuracao do Spotify Developer](#configuracao-do-spotify-developer)
- [Configuracao do Google Cloud (YouTube Music)](#configuracao-do-google-cloud-youtube-music)
- [Teste E2E Real — Spotify](#teste-e2e-real--spotify)
- [Teste E2E Real — YouTube Music](#teste-e2e-real--youtube-music)

---

## Visao Geral

O **Playlist Migration API** recebe um arquivo `.txt` com nomes de musicas (ou um payload JSON), busca cada faixa na API da plataforma escolhida usando fuzzy matching, e cria uma playlist na conta do usuario autenticado.

**Plataformas suportadas:**
- **Spotify** — via Spotify Web API
- **YouTube Music** — via YouTube Data API v3

**O usuario escolhe a plataforma por request** — as plataformas funcionam de forma totalmente independente. Nao e necessario ter conta em ambas.

**Fluxo resumido:**

```
Upload .txt -> Parse -> Celery Task -> Search (API) -> Fuzzy Match -> Create Playlist -> Report
```

O processamento e **assincrono** via Celery — o cliente recebe um `task_id` imediatamente e pode acompanhar o progresso via polling.

---

## Arquitetura

```
                                                          +---------------+
                                                     +--->| Spotify API   |
+---------+     +-----------+     +--------------+   |    +---------------+
| Client  |---->|   Nginx   |---->|   FastAPI    |---+
|         |     | (reverse  |     |  (API x2)    |   |    +---------------+
|         |     |  proxy)   |     |              |   +--->| YouTube API   |
+---------+     +-----------+     +------+-------+   |    +---------------+
                                         |           |
                                         v           |    +---------------+
                                  +--------------+   +--->|    Redis      |
                                  | Celery Worker|        | (broker +     |
                                  |    (x2)      |------->|  backend +    |
                                  +--------------+        |  search cache)|
                                                          +---------------+
```

### Design Patterns

| Padrao | Uso |
|--------|-----|
| **Strategy** | Interface `MusicPlatform` com implementacoes `SpotifyClient` e `YouTubeMusicClient` |
| **Factory** | `PlatformFactory` + `OAuthProviderFactory` — registro dinamico, adicionar nova plataforma = 1 classe + 1 linha |
| **Abstract Base Class** | `OAuthProvider` ABC generaliza o fluxo OAuth para multiplos provedores (Spotify, Google) |
| **Circuit Breaker** | Fail-fast apos falhas consecutivas na API externa |
| **Exponential Backoff** | Retry inteligente com suporte a `Retry-After` header |

---

## Tech Stack

| Componente | Tecnologia | Versao |
|-----------|------------|--------|
| API Framework | FastAPI + Uvicorn | 0.115.6 |
| Task Queue | Celery | 5.4.0 |
| Broker/Backend/Cache | Redis | 7 (Alpine) |
| HTTP Client | httpx (async) | 0.28.1 |
| Fuzzy Matching | RapidFuzz | 3.11.0 |
| Validacao | Pydantic | 2.10.4 |
| Reverse Proxy | Nginx | 1.27 |
| Containerizacao | Docker + Compose | - |
| Testes | Pytest + pytest-asyncio | 8.3.4 |
| Linting | Ruff | 0.8.6 |

---

## Estrutura do Projeto

```
app/
├── main.py                        # Entry point — FastAPI app + factory registrations
├── api/
│   ├── dependencies.py            # Bearer token extraction
│   └── routes/
│       ├── auth.py                # OAuth 2.0 endpoints (multi-platform)
│       └── playlist.py            # Playlist CRUD + task status
├── core/
│   ├── config.py                  # Settings (env vars via Pydantic)
│   └── resilience.py              # Circuit Breaker + Backoff
├── domain/
│   ├── interfaces.py              # MusicPlatform (Strategy interface)
│   └── models.py                  # Track, MatchCandidate, ProcessingResult
├── schemas/
│   ├── auth.py                    # Auth request/response schemas
│   └── playlist.py                # Playlist schemas + PlatformEnum
├── services/
│   ├── oauth/                     # OAuth provider package
│   │   ├── base.py                # OAuthProvider ABC, TokenResponse, OAuthError
│   │   ├── spotify_provider.py    # SpotifyOAuthProvider
│   │   ├── google_provider.py     # GoogleOAuthProvider (YouTube Music)
│   │   └── factory.py             # OAuthProviderFactory
│   ├── spotify_client.py          # Spotify Web API client
│   ├── youtube_music_client.py    # YouTube Data API v3 client
│   ├── search_cache.py            # Redis cache for search results
│   ├── fuzzy_matcher.py           # RapidFuzz multi-strategy matching
│   ├── file_parser.py             # .txt parser (sanitizacao + parsing)
│   ├── platform_factory.py        # Registry-based MusicPlatform factory
│   └── report_generator.py        # Text + JSON report generation
└── workers/
    ├── celery_app.py              # Celery configuration
    └── tasks.py                   # Async task: search + create playlist

tests/
├── conftest.py                    # Fixtures compartilhadas
├── test_phase1_infra.py           # Infraestrutura e boilerplate
├── test_phase2_domain.py          # Domain models e file parser
├── test_phase3_auth.py            # OAuth 2.0 (Spotify + Google + factory)
├── test_phase4_worker.py          # Worker, resilience, SpotifyClient
├── test_phase5_fuzzy.py           # Fuzzy matching + version penalty
├── test_phase6_delivery.py        # Reports e integracao end-to-end
└── test_phase10_youtube.py        # YouTubeMusicClient + SearchCache
```

---

## Instalacao e Setup

### Pre-requisitos

- Python 3.11+
- Redis (ou Docker)
- Conta no [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) e/ou [Google Cloud Console](https://console.cloud.google.com)

### Com Docker

```bash
# 1. Clone o repositorio
git clone https://github.com/GabrielMTTA/playlist-migration-api.git
cd playlist-migration-api

# 2. Configure as variaveis de ambiente
cp .env.example .env
# Edite .env com suas credenciais

# 3. Suba a stack
docker compose up --build -d

# 4. Acesse a API
# http://localhost:8080/docs (Swagger UI)
# http://localhost:8080/health
```

### Sem Docker (Local)

```bash
# 1. Clone e instale as dependencias
git clone https://github.com/GabrielMTTA/playlist-migration-api.git
cd playlist-migration-api
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 2. Configure .env
cp .env.example .env
# Ajuste REDIS_HOST=127.0.0.1 e suas credenciais

# 3. Inicie os 3 servicos (cada um em um terminal)

# Terminal 1: Redis
redis-server --port 6379 --requirepass changeme

# Terminal 2: API
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

# Terminal 3: Celery Worker
celery -A app.workers.celery_app worker --loglevel=info --pool=solo

# 4. Acesse: http://127.0.0.1:8080/docs
```

> **Windows:** Os scripts `.bat` automatizam o passo 3 — basta executar `start_redis.bat`, `start_api.bat` e `start_worker.bat`.

---

## Configuracao

### Variaveis de Ambiente

| Variavel | Padrao | Descricao |
|----------|--------|-----------|
| `DEBUG` | `false` | Habilita Swagger UI (`/docs`) |
| `REDIS_PASSWORD` | `changeme` | Senha do Redis |
| `REDIS_HOST` | `redis` | Host do Redis (`127.0.0.1` para local) |
| `REDIS_PORT` | `6379` | Porta do Redis |
| `SPOTIFY_CLIENT_ID` | — | Client ID do Spotify App |
| `SPOTIFY_CLIENT_SECRET` | — | Client Secret do Spotify App |
| `SPOTIFY_REDIRECT_URI` | `.../api/v1/auth/spotify/callback` | Redirect URI do Spotify |
| `GOOGLE_CLIENT_ID` | — | Client ID do Google OAuth |
| `GOOGLE_CLIENT_SECRET` | — | Client Secret do Google OAuth |
| `GOOGLE_REDIRECT_URI` | `.../api/v1/auth/youtube_music/callback` | Redirect URI do Google |
| `SEARCH_CACHE_TTL` | `86400` | TTL do cache de busca em segundos (24h) |
| `CELERY_BROKER_URL` | *(Redis URL)* | Override opcional do broker |
| `CELERY_RESULT_BACKEND` | *(Redis URL)* | Override opcional do backend |

---

## Endpoints da API

### Health Check

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `GET` | `/health` | Status da aplicacao |

### Autenticacao (OAuth 2.0) — Multi-plataforma

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `GET` | `/api/v1/auth/{platform}/login` | Gera URL de autorizacao |
| `GET` | `/api/v1/auth/{platform}/callback` | Callback OAuth — troca code por tokens |
| `POST` | `/api/v1/auth/{platform}/refresh` | Renova access token expirado |

Onde `{platform}` e `spotify` ou `youtube_music`.

**Fluxo de autenticacao:**

1. `GET /api/v1/auth/spotify/login` — retorna `auth_url` + `state`
2. Redirecione o usuario para `auth_url`
3. Provider redireciona para `/callback?code=...&state=...`
4. Callback retorna `access_token`, `refresh_token`, `expires_in`
5. Use o `access_token` como Bearer token nas requisicoes de playlist

### Playlists

> Todos os endpoints requerem `Authorization: Bearer <access_token>`

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `POST` | `/api/v1/playlists/upload` | Upload de arquivo `.txt` |
| `POST` | `/api/v1/playlists/` | Criar playlist via JSON |
| `GET` | `/api/v1/playlists/tasks/{id}` | Status do processamento |
| `GET` | `/api/v1/playlists/tasks/{id}/report` | Relatorio JSON estruturado |
| `GET` | `/api/v1/playlists/tasks/{id}/report/text` | Relatorio em texto plano |

**Exemplo — Upload para YouTube Music:**

```bash
curl -X POST http://127.0.0.1:8080/api/v1/playlists/upload \
  -H "Authorization: Bearer <youtube_token>" \
  -F "file=@playlist.txt" \
  -F "platform=youtube_music" \
  -F "playlist_name=My Playlist"
```

**Exemplo — Upload para Spotify:**

```bash
curl -X POST http://127.0.0.1:8080/api/v1/playlists/upload \
  -H "Authorization: Bearer <spotify_token>" \
  -F "file=@playlist.txt" \
  -F "platform=spotify" \
  -F "playlist_name=My Playlist"
```

```json
// Response 202
{ "task_id": "a1b2c3d4-...", "message": "Playlist creation job queued" }
```

---

## Formato do Arquivo .txt

```text
# Comentarios sao ignorados (linhas comecando com #)
Radiohead - Creep
Nirvana - Smells Like Teen Spirit
Bohemian Rhapsody
Queen - We Will Rock You
Imagine
```

**Regras:**
- Formato por linha: `Artista - Titulo` ou apenas `Titulo`
- Linhas vazias e comentarios (`#`) sao ignorados
- Maximo: **500 linhas**, **300 caracteres** por linha
- Tamanho maximo do arquivo: **1 MB**
- Encoding: **UTF-8**

---

## Pipeline de Processamento

```
1. PARSE          Arquivo .txt -> lista de Track objects

2. QUEUE          Celery task criada -> task_id retornado ao cliente

3. SEARCH         Para cada track:
                  -> [YouTube] Verifica cache Redis (economia de quota)
                  -> Busca na API da plataforma
                  -> Fuzzy match nos resultados (com version penalty)
                  -> Marca como FOUND/NOT_FOUND/ERROR

4. CREATE         Tracks FOUND -> IDs coletados -> Playlist criada
                  Spotify: batch de 100 tracks
                  YouTube: 1 video por request (limitacao da API)

5. REPORT         ProcessingResult serializado
                  -> Disponivel via /tasks/{id}/report
```

---

## Padroes de Resiliencia

### Exponential Backoff

Retry automatico para status codes retryable (429, 500, 502, 503, 504):

```
Tentativa 0: delay = 1.0s
Tentativa 1: delay = 2.0s
Tentativa 2: delay = 4.0s
Cap: max_delay = 30s
```

- Respeita o header `Retry-After` (rate limiting)
- Configuravel via `BackoffConfig`

### Circuit Breaker

Previne cascata de falhas quando a API externa esta indisponivel:

```
CLOSED  --(falhas)--> OPEN  --(timeout)--> HALF_OPEN
  ^                     |                      |
  +------(sucesso)------+      (sucesso)-------+
```

| Plataforma | Threshold | Recovery Timeout |
|------------|-----------|------------------|
| Spotify | 5 falhas | 60s |
| YouTube Music | 5 falhas | 120s (mais conservador por causa da quota) |

---

## Fuzzy Matching

O sistema usa **3 estrategias combinadas** para validar resultados da busca:

| Estrategia | Peso | Descricao |
|-----------|------|-----------|
| Full Ratio | 45% | Comparacao direta da string completa |
| Token Sort Ratio | 35% | Ignora ordem das palavras |
| Partial Ratio | 20% | Matching de substring |

**Threshold padrao:** 60% de confianca minima para aceitar um match.

### Normalizacao

- Lowercase
- Remocao de acentos (Unicode NFKD)
- Remocao de conteudo entre parenteses/colchetes (remixes, feat., etc.)
- Remocao de caracteres especiais
- Colapso de espacos

### Version Penalty (Penalidade de Versao)

O matcher aplica penalidades automaticas quando o candidato e uma versao diferente do que o usuario pediu:

| Categoria | Keywords detectados | Penalidade | Motivo |
|-----------|-------------------|------------|--------|
| **Hard** | `live`, `ao vivo`, `live at`, `live from`, `live session`, `acoustic`, `remix` | **50%** | Versoes musicalmente diferentes |
| **Soft** | `lyrics`, `lyric video`, `letra`, `legendado`, `traducao`, `traduzida`, `translated` | **15%** | Mesma musica, overlay visual diferente |

**Regra bidirecional:**
- Se o input **nao** menciona "live" mas o candidato tem "Live" no titulo -> penalidade aplicada
- Se o input **menciona** "live" mas o candidato e a versao studio -> penalidade aplicada
- Se ambos coincidem (ou nenhum tem) -> sem penalidade

**Exemplos:**

```
Input:     "Hamurabi"
Candidato: "Hamurabi (Live)" -> penalidade 50% -> studio preferido
Candidato: "Hamurabi"        -> sem penalidade -> selecionado

Input:     "Poppy - New Way Out"
Candidato: "Poppy - New Way Out (Lyric Video)" -> penalidade 15% -> ainda aceito (70.7%)

Input:     "Song (Live)"
Candidato: "Song (Live at Wembley)" -> sem penalidade -> selecionado
Candidato: "Song"                   -> penalidade 50% -> live preferido
```

---

## Search Cache (Redis)

O YouTube Data API v3 tem um **limite de 10.000 unidades/dia**. Cada busca custa 100 unidades, ou seja, uma playlist de 19 tracks consome ~2.900 unidades (search + create + add).

O sistema usa **Redis como cache de busca** para evitar chamadas redundantes:

| Aspecto | Valor |
|---------|-------|
| Key format | `search_cache:{platform}:{query}` |
| TTL | 24 horas (alinhado com o reset de quota do YouTube) |
| Graceful degradation | Se o Redis falhar, o cache e ignorado (log warning) |
| Compartilhamento | Queries identicas entre jobs diferentes usam cache |

**Custo estimado por playlist (19 tracks):**

| Operacao | Units | Com cache miss | Com cache hit |
|----------|-------|---------------|---------------|
| Search | 100 x N | 1.900 | 0 |
| Create playlist | 50 | 50 | 50 |
| Add videos | 50 x N | 950 | 950 |
| **Total** | | **2.900** | **1.000** |

---

## Seguranca

| Camada | Protecao |
|--------|----------|
| **Nginx** | Rate limiting (10 req/s por IP, burst 20), security headers, request size limit (2 MB) |
| **FastAPI** | Validacao de input via Pydantic, sanitizacao de nomes de tracks |
| **OAuth 2.0** | State token para CSRF protection, tokens nunca armazenados no servidor |
| **Google OAuth** | `access_type=offline` + `prompt=consent` garante refresh token |
| **Spotify OAuth** | `show_dialog=true` forca re-autorizacao com scopes corretos |
| **OAuth Package** | Codigo sensivel isolado em `app/services/oauth/` (zona de seguranca) |
| **Docker** | Container roda como non-root user, Redis com senha |
| **Celery** | `task_acks_late=True`, rate limit por task |

---

## Testes

O projeto possui **209 testes** organizados em 7 fases:

| Fase | Arquivo | Testes | Escopo |
|------|---------|--------|--------|
| 1 | `test_phase1_infra.py` | 19 | Health check, Settings, estrutura do projeto |
| 2 | `test_phase2_domain.py` | 35 | Domain models, file parser, MatchCandidate |
| 3 | `test_phase3_auth.py` | 32 | OAuth multi-plataforma (Spotify + Google + factory + rotas) |
| 4 | `test_phase4_worker.py` | 27 | Backoff, Circuit Breaker, SpotifyClient, Celery tasks |
| 5 | `test_phase5_fuzzy.py` | 36 | Fuzzy matching, normalizacao, version penalty |
| 6 | `test_phase6_delivery.py` | 21 | Reports e integracao end-to-end |
| 10 | `test_phase10_youtube.py` | 39 | YouTubeMusicClient, SearchCache, playlist creation |

```bash
# Rodar todos os testes
pytest

# Com coverage
pytest --cov=app --cov-report=html

# Fase especifica
pytest tests/test_phase10_youtube.py -v
```

---

## Configuracao do Spotify Developer

1. Acesse o [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Crie um novo app com nome descritivo
3. Em **Redirect URIs**, adicione: `http://127.0.0.1:8080/api/v1/auth/spotify/callback`
4. Selecione **Web API** como API/SDK utilizada
5. Em **User Management**, adicione o email da conta Spotify que usara o app
6. Copie o **Client ID** e **Client Secret** para o `.env`

> **Development Mode:**
> - Requer **Spotify Premium** na conta do owner
> - Apenas usuarios listados em **User Management** podem usar operacoes de escrita
> - Maximo de **5 usuarios**
> - A API usa endpoints `/me/playlists` e `/playlists/{id}/items` (compativeis com Dev Mode)

---

## Configuracao do Google Cloud (YouTube Music)

1. Acesse o [Google Cloud Console](https://console.cloud.google.com)
2. Crie um novo projeto (ex: "Playlist Migration")
3. Em **APIs & Services > Library**, ative **YouTube Data API v3**
4. Em **APIs & Services > OAuth consent screen**:
   - Tipo: **Externo**
   - Preencha nome, email de suporte e email do developer
   - Em **Test users**, adicione o email da conta Google que usara o app
5. Em **APIs & Services > Credentials**:
   - Crie um **OAuth client ID** (tipo: Web application)
   - Em **Authorized redirect URIs**, adicione: `http://127.0.0.1:8080/api/v1/auth/youtube_music/callback`
6. Copie o **Client ID** e **Client Secret** para o `.env`

> **Quota:**
> - Limite padrao: **10.000 unidades/dia**
> - Cada busca: 100 unidades | Criar playlist: 50 | Adicionar video: 50
> - Uma playlist de 19 tracks custa ~2.900 unidades (~3 playlists/dia)
> - O cache Redis reduz o custo para ~1.000 unidades em buscas repetidas

---

## Teste E2E Real — Spotify

Teste com playlist real de 19 faixas de metalcore/post-hardcore:

| Metrica | Valor |
|---------|-------|
| Total de tracks | 19 |
| Encontradas | 18 |
| Nao encontradas | 1 |
| Taxa de sucesso | **94.7%** |
| Playlist | [Abrir no Spotify](https://open.spotify.com/playlist/0HLLTzqP2AwcvjGmW8r3GC) |

**Desafios superados pelo fuzzy matching:**

| Input (com erros) | Resultado | Confianca |
|-------------------|-----------|-----------|
| `Trivium - Unti   The World Goes Cold` (typo) | Until The World Goes Cold | 98% |
| `TPIY = Left behind` (abreviacao + separador errado) | Left Behind - The Plot In You | 78% |
| `Bring Me The Horizon - DArkSide` (case errado) | DArkSide | 100% |
| `There's No Face - Hamurabi` (sem artista popular) | Hamurabi | 100% |
| `Falling In Reverse - "God Is A Weapon` (aspas soltas) | God Is A Weapon | 100% |

**Limitacao:** `BMTH - Doomed (maphra)` — abreviacoes de banda (BMTH) nao sao resolvidas pela API do Spotify.

---

## Teste E2E Real — YouTube Music

Mesma playlist de 19 faixas, migrada para YouTube Music:

| Metrica | Valor |
|---------|-------|
| Total de tracks | 19 |
| Encontradas | 19 |
| Nao encontradas | 0 |
| Taxa de sucesso | **100%** |
| Playlist | [Abrir no YouTube Music](https://music.youtube.com/playlist?list=PLup2tHzYZNwVGy3Q2zAsf0qskxhgdMqSy) |

**Destaques:**

| Input | Confianca | Observacao |
|-------|-----------|------------|
| `Bring Me The Horizon - Doomed (maphra)` | 100% | Track que falhou no Spotify foi encontrada no YouTube |
| `TPIY = Left behind` | 62.8% | Abreviacao + separador `=` resolvidos |
| `Poppy - New Way Out` | 70.7% | Soft penalty aplicada (lyric video) — ainda aceito |
| `There's No Face - Hamurabi` | 77.3% | Versao studio selecionada (live penalizada) |
| `POPPY, AMY LEE, COURTNEY LAPLANTE - End of You` | 92.2% | Multiplos artistas |
| `Pierce The Veil - King for a Day` | 100% | Match exato |

**Version penalty em acao:**
- `Hamurabi` — versao live disponivel mas studio selecionada (hard penalty 50%)
- `New Way Out` — apenas lyric videos disponiveis, soft penalty (15%) manteve acima do threshold

---

## Extensibilidade

Para adicionar uma nova plataforma (ex: Deezer):

```python
# 1. Criar o client implementando a interface
class DeezerClient(MusicPlatform):
    async def search_track(self, track, access_token): ...
    async def create_playlist(self, name, track_ids, access_token): ...
    async def get_user_id(self, access_token): ...

# 2. Criar o OAuth provider
class DeezerOAuthProvider(OAuthProvider):
    def build_auth_url(self): ...
    async def exchange_code(self, code): ...
    async def refresh_access_token(self, refresh_token): ...

# 3. Adicionar ao enum
class PlatformEnum(str, Enum):
    SPOTIFY = "spotify"
    YOUTUBE_MUSIC = "youtube_music"
    DEEZER = "deezer"  # novo

# 4. Registrar nos factories (app/main.py)
PlatformFactory.register(PlatformEnum.DEEZER, DeezerClient)
OAuthProviderFactory.register(PlatformEnum.DEEZER, DeezerOAuthProvider)
```

Nenhuma alteracao necessaria na logica de processamento, workers, rotas ou fuzzy matching.

---

## Licenca

Este projeto e de uso pessoal/educacional.

---

<p align="center">
  Desenvolvido com FastAPI, Celery e RapidFuzz<br>
  <sub>Co-Authored-By: Claude Opus 4.6</sub>
</p>
