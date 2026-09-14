{{- define "ai.deployment" -}}
{{- range $name := list "ollama" "odysseus" "chroma" "searx" "configure" }}
{{- $image := required (printf "Reviewed %s image required" $name) (index $.Values.images $name) }}
{{- if not (regexMatch "^[^\\s@]+@sha256:[a-f0-9]{64}$" $image) }}{{ fail "Every AI image must use a reviewed SHA-256 digest" }}{{ end }}
{{- end }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-runtime
  namespace: homelab-models
  annotations:
    homelab/desired-state: 'off'
    homelab/command-revision: '0'
spec:
  replicas: 0
  strategy: {type: Recreate}
  selector:
    matchLabels: {app: ai-runtime}
  template:
    metadata:
      labels: {app: ai-runtime}
    spec:
      hostUsers: false
      automountServiceAccountToken: false
      nodeSelector: {kubernetes.io/hostname: {{ .Values.node }}}
      imagePullSecrets: [{name: ghcr-read}]
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile: {type: RuntimeDefault}
      initContainers:
        - name: configure-search
          image: {{ .Values.images.configure | quote }}
          command: [python, -B, -c]
          args:
            - |
              import json, os, pathlib
              pathlib.Path('/config/settings.yml').write_text(
                  'use_default_settings: true\nserver:\n  secret_key: ' +
                  json.dumps(os.environ['SEARXNG_SECRET']) +
                  '\n  limiter: false\n  image_proxy: false\nsearch:\n  formats: [html, json]\n')
          env:
            - name: SEARXNG_SECRET
              valueFrom:
                secretKeyRef: {name: odysseus-bootstrap, key: searxng-secret}
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          resources:
            requests: {cpu: 100m, memory: 64Mi, ephemeral-storage: 16Mi}
            limits: {cpu: 100m, memory: 64Mi, ephemeral-storage: 16Mi}
          volumeMounts: [{name: search-config, mountPath: /config}]
      containers:
        - name: ollama
          image: {{ .Values.images.ollama | quote }}
          args: [serve]
          ports: [{name: model-raw, containerPort: 11435}]
          env:
            - {name: HOME, value: /models}
            - {name: OLLAMA_HOST, value: '0.0.0.0:11435'}
            - {name: OLLAMA_MODELS, value: /models/models}
            - {name: OLLAMA_MAX_LOADED_MODELS, value: '1'}
            - {name: OLLAMA_NUM_PARALLEL, value: '1'}
            - {name: OLLAMA_CONTEXT_LENGTH, value: '4096'}
            - {name: OLLAMA_KEEP_ALIVE, value: '5m'}
            - {name: OLLAMA_MAX_QUEUE, value: '16'}
            - {name: OLLAMA_NO_CLOUD, value: 'true'}
          resources:
            requests: {cpu: '34', memory: 64Gi, ephemeral-storage: 256Mi}
            limits: {cpu: '34', memory: 64Gi, ephemeral-storage: 2Gi}
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          startupProbe:
            httpGet: {path: /api/version, port: model-raw}
            periodSeconds: 5
            failureThreshold: 120
          readinessProbe:
            httpGet: {path: /api/version, port: model-raw}
          volumeMounts:
            - {name: models, mountPath: /models}
            - {name: ollama-tmp, mountPath: /tmp}
        - name: odysseus
          image: {{ .Values.images.odysseus | quote }}
          ports: [{name: workspace, containerPort: 7000}]
          env:
            - {name: OLLAMA_HOST, value: 'http://ai-model-gateway:11434'}
            - {name: OLLAMA_BASE_URL, value: 'http://ai-model-gateway:11434/v1'}
            - {name: LLM_HOST, value: ai-model-gateway}
            - {name: RESEARCH_LLM_ENDPOINT, value: 'http://ai-model-gateway:11434/v1/chat/completions'}
            - {name: SEARXNG_INSTANCE, value: 'http://127.0.0.1:8080'}
            - {name: CHROMADB_HOST, value: '127.0.0.1'}
            - {name: CHROMADB_PORT, value: '8000'}
            - {name: ODYSSEUS_DATA_DIR, value: /workspace/data}
            - {name: DATABASE_URL, value: 'sqlite:////workspace/data/app.db'}
            - {name: AUTH_ENABLED, value: 'true'}
            - {name: LOCALHOST_BYPASS, value: 'false'}
            - {name: SECURE_COOKIES, value: 'true'}
            - {name: ALLOWED_ORIGINS, value: 'https://odysseus.tail2f646b.ts.net'}
            - {name: OAUTH_REDIRECT_BASE_URL, value: 'https://odysseus.tail2f646b.ts.net'}
            - {name: FASTEMBED_CACHE_PATH, value: /workspace/cache/fastembed}
            - {name: ODYSSEUS_ADMIN_USER, value: admin}
            - name: ODYSSEUS_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef: {name: odysseus-bootstrap, key: admin-password}
          resources:
            requests: {cpu: '1', memory: 8Gi, ephemeral-storage: 256Mi}
            limits: {cpu: '1', memory: 8Gi, ephemeral-storage: 2Gi}
          securityContext:
            # Cookbook installs tools in /app; writable space has an eviction limit.
            # trivy:ignore:AVD-KSV-0014
            readOnlyRootFilesystem: false
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          startupProbe:
            tcpSocket: {port: workspace}
            periodSeconds: 5
            failureThreshold: 120
          readinessProbe:
            tcpSocket: {port: workspace}
          volumeMounts:
            - {name: workspace, mountPath: /workspace}
            - {name: workspace-tmp, mountPath: /tmp}
        - name: chroma
          image: {{ .Values.images.chroma | quote }}
          args: [run, --path, /data, --host, '0.0.0.0', --port, '8000']
          ports: [{name: vector, containerPort: 8000}]
          startupProbe:
            tcpSocket: {port: vector}
            periodSeconds: 5
            failureThreshold: 120
          readinessProbe:
            tcpSocket: {port: vector}
          env:
            - {name: CHROMA_PERSIST_PATH, value: /data}
            - {name: ANONYMIZED_TELEMETRY, value: 'false'}
          resources:
            requests: {cpu: 500m, memory: 4Gi, ephemeral-storage: 256Mi}
            limits: {cpu: 500m, memory: 4Gi, ephemeral-storage: 2Gi}
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          volumeMounts:
            - {name: vector, mountPath: /data}
            - {name: vector-tmp, mountPath: /tmp}
        - name: searx
          image: {{ .Values.images.searx | quote }}
          command: [/usr/local/searxng/.venv/bin/granian]
          args: [--interface, wsgi, --host, '0.0.0.0', --port, '8080', 'searx.webapp:app']
          ports: [{name: search, containerPort: 8080}]
          startupProbe:
            tcpSocket: {port: search}
            periodSeconds: 5
            failureThreshold: 120
          readinessProbe:
            tcpSocket: {port: search}
          env:
            - {name: SEARXNG_SETTINGS_PATH, value: /etc/searxng/settings.yml}
            - {name: SEARXNG_BASE_URL, value: 'http://127.0.0.1:8080/'}
          resources:
            requests: {cpu: 250m, memory: 1Gi, ephemeral-storage: 256Mi}
            limits: {cpu: 250m, memory: 1Gi, ephemeral-storage: 2Gi}
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          volumeMounts:
            - {name: search-config, mountPath: /etc/searxng, readOnly: true}
            - {name: search-cache, mountPath: /var/cache/searxng}
            - {name: search-tmp, mountPath: /tmp}
      volumes:
        {{- range $name, $_ := .Values.volumes }}
        - name: {{ $name }}
          persistentVolumeClaim: {claimName: ai-{{ $name }}}
        {{- end }}
        {{- range $name := list "ollama-tmp" "workspace-tmp" "vector-tmp" "search-tmp" "search-cache" }}
        - name: {{ $name }}
          emptyDir: {sizeLimit: 512Mi}
        {{- end }}
        - name: search-config
          emptyDir: {sizeLimit: 1Mi}
{{- end -}}
