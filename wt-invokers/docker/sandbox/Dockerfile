FROM ghcr.io/prefix-dev/pixi:latest

ENV PATH="/root/.pixi/bin:${PATH}"

RUN pixi global install \
    -c https://prefix.dev/ecoscope-workflows \
    -c conda-forge \
    wt-invokers
RUN mkdir -p /work /results

ENTRYPOINT ["wt-invokers.sandbox"]
