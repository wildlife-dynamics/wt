ARG PIXI_BASE_IMAGE=ghcr.io/prefix-dev/pixi:0.78.0
FROM ${PIXI_BASE_IMAGE}

ARG WT_INVOKERS_VERSION
ENV PATH="/root/.pixi/bin:${PATH}"

RUN pixi global install \
    -c https://prefix.dev/ecoscope-workflows \
    -c conda-forge \
    wt-invokers==${WT_INVOKERS_VERSION}
RUN mkdir -p /work /results

ENTRYPOINT ["wt-invokers.sandbox"]
