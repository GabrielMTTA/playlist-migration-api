# 🎵 Playlist Migration API

Backend API para migração de playlists a partir de arquivos `.txt` para plataformas de streaming. Atualmente suporta **Spotify**, com arquitetura extensível para futuras plataformas (YouTube Music, Deezer, etc.).

> **Status:** Backend completo com 142 testes passando. Requer Spotify Premium para uso em produção (limitação da API do Spotify para apps em Development Mode).

---

## Índice

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Tech Stack](#tech-stack)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Instalação e Setup](#instalação-e-setup)
  - [Com Docker](#com-docker)
  - [Sem Docker (Local)](#sem-docker-local)
- [Configuração](#configuração)
- [Endpoints da API](#endpoints-da-api)
  - [Autenticação (OAuth 2.0)](#autenticação-oauth-20)
  - [Playlists](#playlists)
  - [Health Check](#health-check)
- [Formato do Arquivo .txt](#formato-do-arquivo-txt)
- [Pipeline de Processamento](#pipeline-de-processamento)
- [Padrões de Resiliência](#padrões-de-resiliência)
- [Fuzzy Matching](#fuzzy-matching)
- [Segurança](#segurança)
- [Testes](#testes)
- [Configuração do Spotify Developer](#configuração-do-spotify-developer)

---

## Visão Geral

O **Playlist Migration API** recebe um arquivo `.txt` com nomes de músicas (ou um payload JSON), busca cada faixa na API do Spotify usando fuzzy matching, e cria uma playlist na conta do usuário autenticado.

**Fluxo resumido:**

```
Upload .txt → Parse → Celery Task → Search (Spotify API) → Fuzzy Match → Create Playlist → Report
```

O processamento é **assíncrono** via Celery — o cliente recebe um `task_id` imediatamente e pode acompanhar o progresso via polling.

---

## Arquitetura

```
┌─────────┐     ┌───────────┐     ┌──────────────┐     ┌─────────┐
│  Client  │────▶│   Nginx   │────▶│   FastAPI    │────▶│  Redis  │
│          │     │ (reverse  │     │  (API x2)    │     │ (broker │
│          │     │  proxy)   │     │              │     │  + backend)
└─────────┘     └───────────┘     └──────┬───────┘     └────┬────┘
                                         │                   │
                                         │    ┌──────────────┘
                                         ▼    ▼
                                  ┌──────────────┐     ┌─────────────┐
                                  │ Celery Worker │────▶│ Spotify API │
                                  │    (x2)       │     │             │
                                  └──────────────┘     └─────────────┘
```

### Design Patterns

| Padrão | Uso |
|--------|-----|
| **Strategy** | Interface `MusicPlatform` com implementação `SpotifyClient` — desacopla a lógica de processamento da plataforma |
| **Factory** | `PlatformFactory` com registro dinâmico — adicionar nova plataforma = 1 classe + 1 linha de registro |
| **Circuit Breaker** | Fail-fast após falhas consecutivas na API externa |
| **Exponential Backoff** | Retry inteligente com suporte a `Retry-After` header |

---

## Tech Stack

| Componente | Tecnologia | Versão |
|-----------|------------|--------|
| API Framework | FastAPI + Uvicorn | 0.115.6 |
| Task Queue | Celery | 5.4.0 |
| Broker/Backend | Redis | 7 (Alpine) |
| HTTP Client | httpx (async) | 0.28.1 |
| Fuzzy Matching | RapidFuzz | 3.11.0 |
| Validação | Pydantic | 2.10.4 |
| Reverse Proxy | Nginx | 1.27 |
| Containerização | Docker + Compose | - |
| Testes | Pytest + pytest-asyncio | 8.3.4 |
| Linting | Ruff | 0.8.6 |

---

## Estrutura do Projeto

```
├── app/
│   ├── main.py                    # Entry point — FastAPI app
│   ├── api/
│   │   ├── dependencies.py        # Bearer token extraction
│   │   └── routes/
│   │       ├── auth.py            # OAuth 2.0 endpoints
│   │       └── playlist.py        # Playlist CRUD + task status
│   ├── core/
│   │   ├── config.py              # Settings (env vars via Pydantic)
│   │   └── resilience.py          # Circuit Breaker + Backoff
│   ├── domain/
│   │   ├── interfaces.py          # MusicPlatform (Strategy interface)
│   │   └── models.py              # Track, PlaylistRequest, ProcessingResult
│   ├── schemas/
│   │   ├── auth.py                # Auth request/response schemas
│   │   └── playlist.py            # Playlist schemas + PlatformEnum
│   ├── services/
│   │   ├── file_parser.py         # .txt parser (sanitização + parsing)
│   │   ├── fuzzy_matcher.py       # RapidFuzz multi-strategy matching
│   │   ├── platform_factory.py    # Registry-based factory
│   │   ├── report_generator.py    # Text + JSON report generation
│   │   ├── spotify_auth.py        # Spotify OAuth 2.0 service
│   │   └── spotify_client.py      # Spotify Web API client
│   └── workers/
│       ├── celery_app.py          # Celery configuration
│       └── tasks.py               # Async task: search + create playlist
├── tests/
│   ├── conftest.py                # Fixtures compartilhadas
│   ├── test_phase1_infra.py       # Infraestrutura e boilerplate
│   ├── test_phase2_domain.py      # Domain models e file parser
│   ├── test_phase3_auth.py        # OAuth 2.0 flow
│   ├── test_phase4_worker.py      # Worker, resilience, SpotifyClient
│   ├── test_phase5_fuzzy.py       # Fuzzy matching
│   └── test_phase6_delivery.py    # Reports e integração end-to-end
├── nginx/
│   └── nginx.conf                 # Rate limiting, security headers, proxy
├── Dockerfile                     # Multi-stage (api + worker targets)
├── docker-compose.yml             # Full stack orchestration
├── requirements.txt               # Python dependencies
├── .env.example                   # Template de variáveis de ambiente
├── start_api.bat                  # Windows: iniciar API local
├── start_redis.bat                # Windows: iniciar Redis local
└── start_worker.bat               # Windows: iniciar Celery worker local
```

---

## Instalação e Setup

### Pré-requisitos

- Python 3.12+
- Redis (ou Docker)
- Conta no [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)

### Com Docker

```bash
# 1. Clone o repositório
git clone https://github.com/GabrielMTTA/playlist-migration-api.git
cd playlist-migration-api

# 2. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com suas credenciais do Spotify

# 3. Suba a stack
docker compose up --build -d

# 4. Acesse a API
# http://localhost:8080/docs (Swagger UI)
# http://localhost:8080/health
```

A stack Docker inclui:
- **Nginx** (porta 8080) — reverse proxy com rate limiting
- **API** (x2 réplicas) — FastAPI
- **Worker** (x2 réplicas) — Celery
- **Redis** — broker + result backend

### Sem Docker (Local)

```bash
# 1. Clone e instale as dependências
git clone https://github.com/GabrielMTTA/playlist-migration-api.git
cd playlist-migration-api
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 2. Configure .env
cp .env.example .env
# Ajuste REDIS_HOST=127.0.0.1 e suas credenciais Spotify

# 3. Inicie os 3 serviços (cada um em um terminal)

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

## Configuração

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `DEBUG` | `false` | Habilita Swagger UI (`/docs`) |
| `REDIS_PASSWORD` | `changeme` | Senha do Redis |
| `REDIS_HOST` | `redis` | Host do Redis (`127.0.0.1` para local) |
| `REDIS_PORT` | `6379` | Porta do Redis |
| `SPOTIFY_CLIENT_ID` | — | Client ID do Spotify App |
| `SPOTIFY_CLIENT_SECRET` | — | Client Secret do Spotify App |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8080/api/v1/auth/callback` | Redirect URI (deve bater com o Dashboard) |
| `CELERY_BROKER_URL` | *(Redis URL)* | Override opcional do broker |
| `CELERY_RESULT_BACKEND` | *(Redis URL)* | Override opcional do backend |

---

## Endpoints da API

### Health Check

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Status da aplicação |

```json
// Response 200
{ "status": "healthy" }
```

### Autenticação (OAuth 2.0)

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/v1/auth/login` | Gera URL de autorização do Spotify |
| `GET` | `/api/v1/auth/callback` | Callback OAuth — troca code por tokens |
| `POST` | `/api/v1/auth/refresh` | Renova access token expirado |

**Fluxo de autenticação:**

1. `GET /api/v1/auth/login` → retorna `auth_url` + `state`
2. Redirecione o usuário para `auth_url`
3. Spotify redireciona para `/callback?code=...&state=...`
4. Callback retorna `access_token`, `refresh_token`, `expires_in`
5. Use o `access_token` como Bearer token nas requisições de playlist

### Playlists

> Todos os endpoints de playlist requerem `Authorization: Bearer <access_token>`

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/v1/playlists/upload` | Upload de arquivo `.txt` |
| `POST` | `/api/v1/playlists/` | Criar playlist via JSON |
| `GET` | `/api/v1/playlists/tasks/{id}` | Status do processamento |
| `GET` | `/api/v1/playlists/tasks/{id}/report` | Relatório JSON estruturado |
| `GET` | `/api/v1/playlists/tasks/{id}/report/text` | Relatório em texto plano |

**Exemplo — Upload de arquivo:**

```bash
curl -X POST http://127.0.0.1:8080/api/v1/playlists/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@playlist.txt" \
  -F "platform=spotify" \
  -F "playlist_name=My Playlist"
```

```json
// Response 202
{ "task_id": "a1b2c3d4-...", "message": "Playlist creation job queued" }
```

**Exemplo — JSON payload:**

```bash
curl -X POST http://127.0.0.1:8080/api/v1/playlists/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "spotify",
    "playlist_name": "Rock Classics",
    "track_names": ["Radiohead - Creep", "Nirvana - Smells Like Teen Spirit"]
  }'
```

**Exemplo — Polling de status:**

```json
// GET /api/v1/playlists/tasks/{task_id}

// Em processamento
{ "task_id": "...", "status": "processing", "result": { "current": 5, "total": 10, "found": 3 } }

// Completo
{ "task_id": "...", "status": "completed", "result": { "total": 10, "found": 8, "not_found": 2, "errors": 0, "success_rate": 80.0, "playlist_url": "https://open.spotify.com/playlist/..." } }
```

**Exemplo — Relatório em texto:**

```
============================================================
  PLAYLIST MIGRATION REPORT
  Generated: 2026-04-02 15:30:00 UTC
============================================================

SUMMARY
----------------------------------------
  Total tracks:     10
  Found:            8
  Not found:        2
  Errors:           0
  Success rate:     80.0%

  Playlist URL: https://open.spotify.com/playlist/abc123

TRACK DETAILS
----------------------------------------
  FOUND (8):
    [OK]  Radiohead - Creep  (confidence: 95%, uri: spotify:track:...)
    [OK]  Nirvana - Smells Like Teen Spirit  (confidence: 92%, uri: spotify:track:...)
    ...
  NOT FOUND (2):
    [--]  Unknown Artist - Mystery Song  (best match confidence: 45%)
    ...

============================================================
```

---

## Formato do Arquivo .txt

```text
# Comentários são ignorados (linhas começando com #)
Radiohead - Creep
Nirvana - Smells Like Teen Spirit
Bohemian Rhapsody
Queen - We Will Rock You
Imagine
```

**Regras:**
- Formato por linha: `Artista - Título` ou apenas `Título`
- Linhas vazias e comentários (`#`) são ignorados
- Máximo: **500 linhas**, **300 caracteres** por linha
- Tamanho máximo do arquivo: **1 MB**
- Encoding: **UTF-8**
- Caracteres de controle são automaticamente removidos

---

## Pipeline de Processamento

```
1. PARSE          Arquivo .txt → lista de Track objects
                  (sanitização, validação, split artist/title)

2. QUEUE          Celery task criada → task_id retornado ao cliente
                  (processamento assíncrono)

3. SEARCH         Para cada track:
                  → Busca na Spotify Search API
                  → Fuzzy match nos resultados
                  → Marca como FOUND/NOT_FOUND/ERROR

4. CREATE         Tracks FOUND → URI coletadas → Playlist criada
                  (batch de 100 tracks por request)

5. REPORT         ProcessingResult serializado
                  → Disponível via /tasks/{id}/report
```

**Progress tracking:** O worker atualiza o estado da task a cada track processada, permitindo ao cliente acompanhar o progresso em tempo real via polling.

---

## Padrões de Resiliência

### Exponential Backoff

Retry automático para status codes retryable (429, 500, 502, 503, 504):

```
Tentativa 0: delay = 1.0s
Tentativa 1: delay = 2.0s
Tentativa 2: delay = 4.0s
Tentativa 3: delay = 8.0s
...
Cap: max_delay = 30s
```

- Respeita o header `Retry-After` do Spotify (rate limiting)
- Configurável via `BackoffConfig`

### Circuit Breaker

Previne cascata de falhas quando a API externa está indisponível:

```
CLOSED  ──(5 falhas)──▶  OPEN  ──(60s timeout)──▶  HALF_OPEN
   ▲                       │                           │
   │                       │                           │
   └──(sucesso)────────────┘     ┌─(sucesso)───────────┘
                                 │
                                 ▼
                              CLOSED
```

| Estado | Comportamento |
|--------|--------------|
| **CLOSED** | Requests passam normalmente; falhas são contadas |
| **OPEN** | Requests bloqueados imediatamente (fail-fast) |
| **HALF_OPEN** | 1 request de teste permitido; sucesso fecha, falha reabre |

---

## Fuzzy Matching

O sistema usa **3 estratégias combinadas** para validar resultados da busca:

| Estratégia | Peso | Descrição |
|-----------|------|-----------|
| Full Ratio | 45% | Comparação direta da string completa |
| Token Sort Ratio | 35% | Ignora ordem das palavras |
| Partial Ratio | 20% | Matching de substring |

**Threshold padrão:** 60% de confiança mínima para aceitar um match.

**Normalização aplicada:**
- Lowercase
- Remoção de acentos (Unicode NFKD)
- Remoção de conteúdo entre parênteses/colchetes (remixes, feat., etc.)
- Remoção de caracteres especiais
- Colapso de espaços

**Exemplo:**
```
Input:    "Radiohead - Creep (Acoustic Version)"
Spotify:  "Creep" by Radiohead
Score:    95.2% → FOUND ✓
```

---

## Segurança

| Camada | Proteção |
|--------|----------|
| **Nginx** | Rate limiting (10 req/s por IP, burst 20), security headers (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy), request size limit (2 MB) |
| **FastAPI** | Validação de input via Pydantic, sanitização de nomes de tracks (max 300 chars), validação de file type e encoding |
| **File Parser** | Remoção de caracteres de controle, limite de 500 linhas, comentários ignorados |
| **OAuth 2.0** | State token para CSRF protection, tokens nunca armazenados no servidor |
| **Docker** | Container roda como non-root user (`appuser`), Redis com senha |
| **Celery** | `task_acks_late=True` (garante reprocessamento em caso de crash), rate limit por task |

---

## Testes

O projeto possui **142 testes** organizados em 6 fases:

| Fase | Arquivo | Testes | Escopo |
|------|---------|--------|--------|
| 1 | `test_phase1_infra.py` | 19 | Health check, Settings, estrutura do projeto |
| 2 | `test_phase2_domain.py` | 35 | Domain models, file parser, sanitização |
| 3 | `test_phase3_auth.py` | 18 | OAuth 2.0 flow (login, callback, refresh) |
| 4 | `test_phase4_worker.py` | 27 | Backoff, Circuit Breaker, SpotifyClient, Celery tasks |
| 5 | `test_phase5_fuzzy.py` | 22 | Fuzzy matching, normalização, edge cases |
| 6 | `test_phase6_delivery.py` | 21 | Reports, integração end-to-end, schemas |

```bash
# Rodar todos os testes
pytest

# Com coverage
pytest --cov=app --cov-report=html

# Fase específica
pytest tests/test_phase4_worker.py -v
```

---

## Configuração do Spotify Developer

1. Acesse o [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Crie um novo app com nome descritivo
3. Em **Redirect URIs**, adicione: `http://127.0.0.1:8080/api/v1/auth/callback`
4. Selecione **Web API** como API utilizada
5. Copie o **Client ID** e **Client Secret** para o `.env`

> **Nota:** Apps em Development Mode requerem que o owner tenha **Spotify Premium** para acessar a Web API (Search, Create Playlist). Sem Premium, a API retorna 403 Forbidden.

---

## Extensibilidade

Para adicionar uma nova plataforma (ex: YouTube Music):

```python
# 1. Criar o client implementando a interface
class YouTubeClient(MusicPlatform):
    async def search_track(self, track: Track, access_token: str) -> Track: ...
    async def create_playlist(self, name: str, track_ids: list[str], access_token: str) -> str: ...
    async def get_user_id(self, access_token: str) -> str: ...

# 2. Adicionar ao enum
class PlatformEnum(str, Enum):
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"  # novo

# 3. Registrar no factory (app/main.py)
PlatformFactory.register(PlatformEnum.YOUTUBE, YouTubeClient)
```

Nenhuma alteração necessária na lógica de processamento, workers ou routes.

---

## Licença

Este projeto é de uso pessoal/educacional.

---

<p align="center">
  Desenvolvido com FastAPI, Celery e RapidFuzz<br>
  <sub>Co-Authored-By: Claude Opus 4.6</sub>
</p>
