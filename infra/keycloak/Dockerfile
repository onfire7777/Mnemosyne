# Optimized production Keycloak image (canonical two-stage pattern).
# Build-stage options (db vendor, health) are baked here so the runtime can
# `start --optimized` on a read-only rootfs with no boot-time augmentation.
FROM quay.io/keycloak/keycloak:25.0 AS builder
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:25.0
COPY --from=builder /opt/keycloak/lib/quarkus/ /opt/keycloak/lib/quarkus/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
