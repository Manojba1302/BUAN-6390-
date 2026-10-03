# Official MinIO release instructions now require building containers from source.
# Pin the security release rather than depend on removed prebuilt images.
FROM golang:1.24.8-alpine AS build
ENV CGO_ENABLED=0
RUN go install github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z
FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl && addgroup -g 10001 minio && adduser -D -u 10001 -G minio minio && mkdir /data && chown minio:minio /data
COPY --from=build /go/bin/minio /usr/local/bin/minio
USER minio
EXPOSE 9000
ENTRYPOINT ["minio"]
CMD ["server", "/data"]
