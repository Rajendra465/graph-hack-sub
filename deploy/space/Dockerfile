# Codebook's live view as a Hugging Face Space: FalkorDB 6.0.2 and the app in one container.
# Built from deploy/out/space/, which deploy/build_space.sh assembles: app/ is the repo at HEAD plus the
# bots' word vectors, and falkordb/dump.rdb is a snapshot of the memories behind the published results.
FROM falkordb/falkordb:6.0.2

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

# Hugging Face runs the container as user 1000.
RUN useradd --create-home --uid 1000 user
ENV HOME=/home/user \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /home/user/app
COPY --chown=user:user app/ ./
RUN uv sync --frozen --no-dev --python 3.12 && chown -R user:user /home/user/app
COPY --chown=user:user falkordb/dump.rdb /home/user/falkordb/dump.rdb
COPY --chown=user:user start.sh /home/user/start.sh

USER user
ENV CODEBOOK_HOME=/home/user/app \
    CODEBOOK_UI_HOST=0.0.0.0 \
    CODEBOOK_UI_PORT=7860 \
    CODEBOOK_DB_PORT=6390 \
    CODEBOOK_PUBLIC_HOST=sarpal465-codebook.hf.space
EXPOSE 7860
ENTRYPOINT []
CMD ["bash", "/home/user/start.sh"]
