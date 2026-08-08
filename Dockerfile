FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Fontes base do sistema (sempre presentes em qualquer Debian).
# fonts-liberation fornece Liberation Sans/Mono/Serif — substitutos
# métricamente idênticos de Arial, Helvetica, Courier, Times. Libass usa.
# O yt-dlp precisa de um RUNTIME de JavaScript para resolver o n-signature challenge
# do YouTube (sistema EJS). ⚠️ `nodejs` do Debian bookworm NÃO serve: é a v18, e o EJS
# exige Node >= 22.0.0 — e ainda assim precisaria da flag `--js-runtimes node`.
# Deno é o runtime PADRÃO do yt-dlp (auto-detectado, sem flag) e executa o solver com
# permissões restritas. O nodejs fica só como utilitário geral.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-liberation \
        fonts-dejavu-core \
        fonts-noto-core \
        curl \
        unzip \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# Deno — sem ele (ou sem Node >= 22) o /download morre em "n challenge solving failed"
# e o yt-dlp enxerga só formatos de imagem. Medido no Railway em 2026-08-07.
ARG CACHE_BUST=2026-08-08-deno
ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh -s -- --yes \
    && deno --version

# Google Fonts baixadas do github.com/google/fonts.
# Cada curl roda isolado: se uma quebrar, as outras continuam.
# URLs de fontes variáveis usam %5B/%5D (encoding de [ e ]).
RUN mkdir -p /usr/share/fonts/truetype/app && \
    cd /usr/share/fonts/truetype/app && \
    BASE="https://raw.githubusercontent.com/google/fonts/main" && \
    echo "=== Baixando Google Fonts (failures são loggados, não matam build) ===" && \
    ( \
      curl -fsSL "$BASE/ofl/montserrat/Montserrat%5Bwght%5D.ttf"            -o Montserrat.ttf           || echo "[WARN] Montserrat"; \
      curl -fsSL "$BASE/ofl/roboto/Roboto%5Bwdth,wght%5D.ttf"               -o Roboto.ttf               || echo "[WARN] Roboto"; \
      curl -fsSL "$BASE/ofl/oswald/Oswald%5Bwght%5D.ttf"                    -o Oswald.ttf               || echo "[WARN] Oswald"; \
      curl -fsSL "$BASE/ofl/raleway/Raleway%5Bwght%5D.ttf"                  -o Raleway.ttf              || echo "[WARN] Raleway"; \
      curl -fsSL "$BASE/ofl/nunito/Nunito%5Bwght%5D.ttf"                    -o Nunito.ttf               || echo "[WARN] Nunito"; \
      curl -fsSL "$BASE/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf"  -o PlayfairDisplay.ttf      || echo "[WARN] PlayfairDisplay"; \
      curl -fsSL "$BASE/ofl/opensans/OpenSans%5Bwdth,wght%5D.ttf"           -o OpenSans.ttf             || echo "[WARN] OpenSans"; \
      curl -fsSL "$BASE/ofl/poppins/Poppins-Regular.ttf"                    -o Poppins-Regular.ttf      || echo "[WARN] Poppins-Regular"; \
      curl -fsSL "$BASE/ofl/poppins/Poppins-Bold.ttf"                       -o Poppins-Bold.ttf         || echo "[WARN] Poppins-Bold"; \
      curl -fsSL "$BASE/ofl/poppins/Poppins-Black.ttf"                      -o Poppins-Black.ttf        || echo "[WARN] Poppins-Black"; \
      curl -fsSL "$BASE/ofl/lato/Lato-Regular.ttf"                          -o Lato-Regular.ttf         || echo "[WARN] Lato-Regular"; \
      curl -fsSL "$BASE/ofl/lato/Lato-Bold.ttf"                             -o Lato-Bold.ttf            || echo "[WARN] Lato-Bold"; \
      curl -fsSL "$BASE/ofl/bebasneue/BebasNeue-Regular.ttf"                -o BebasNeue-Regular.ttf    || echo "[WARN] BebasNeue"; \
      curl -fsSL "$BASE/ofl/anton/Anton-Regular.ttf"                        -o Anton-Regular.ttf        || echo "[WARN] Anton"; \
      curl -fsSL "$BASE/ofl/bangers/Bangers-Regular.ttf"                    -o Bangers-Regular.ttf      || echo "[WARN] Bangers"; \
      curl -fsSL "$BASE/apache/permanentmarker/PermanentMarker-Regular.ttf" -o PermanentMarker-Regular.ttf || echo "[WARN] PermanentMarker"; \
      curl -fsSL "$BASE/ofl/lobster/Lobster-Regular.ttf"                    -o Lobster-Regular.ttf      || echo "[WARN] Lobster"; \
    ) && \
    echo "=== Fontes instaladas: ===" && \
    ls -la /usr/share/fonts/truetype/app/ && \
    fc-cache -fv

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.py .
COPY templates/ templates/

EXPOSE 5000

CMD ["python", "start.py"]
