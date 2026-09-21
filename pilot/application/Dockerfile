FROM docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0
COPY www /www
USER 65534:65534
EXPOSE 8080
CMD ["sh", "-c", "echo 'pilot-observe http-v1-started'; exec httpd -f -p 8080 -h /www"]
