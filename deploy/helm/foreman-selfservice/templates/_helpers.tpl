{{/* Chart name. */}}
{{- define "foreman-selfservice.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Fully qualified application name. */}}
{{- define "foreman-selfservice.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "foreman-selfservice.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "foreman-selfservice.labels" -}}
helm.sh/chart: {{ include "foreman-selfservice.chart" . }}
app.kubernetes.io/name: {{ include "foreman-selfservice.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "foreman-selfservice.selectorLabels" -}}
app.kubernetes.io/name: {{ include "foreman-selfservice.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "foreman-selfservice.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "foreman-selfservice.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "foreman-selfservice.image" -}}
{{- if .Values.image.digest -}}
{{ printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end -}}
{{- end }}

{{- define "foreman-selfservice.chikletConfigMapName" -}}
{{- if eq .Values.chiklets.mode "existingConfigMap" -}}
{{ required "chiklets.existingConfigMap is required when chiklets.mode=existingConfigMap" .Values.chiklets.existingConfigMap }}
{{- else -}}
{{ include "foreman-selfservice.fullname" . }}-chiklets
{{- end -}}
{{- end }}

{{- define "foreman-selfservice.commonEnvFrom" -}}
- configMapRef:
    name: {{ include "foreman-selfservice.fullname" . }}
- secretRef:
    name: {{ required "secrets.existingSecret is required" .Values.secrets.existingSecret }}
{{- end }}

{{- define "foreman-selfservice.commonEnv" -}}
- name: RUN_MIGRATIONS
  value: "false"
- name: CHIKLET_DIRECTORY
  value: {{ .Values.chiklets.mountPath | quote }}
{{- if .Values.foremanCa.existingConfigMap }}
- name: FOREMAN_CA_BUNDLE
  value: "/app/secrets/ca/foreman-ca.pem"
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "foreman-selfservice.commonVolumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- if ne .Values.chiklets.mode "image" }}
- name: chiklets
  mountPath: {{ .Values.chiklets.mountPath }}
  readOnly: true
{{- end }}
{{- if .Values.foremanCa.existingConfigMap }}
- name: foreman-ca
  mountPath: /app/secrets/ca
  readOnly: true
{{- end }}
{{- with .Values.extraVolumeMounts }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "foreman-selfservice.commonVolumes" -}}
- name: tmp
  emptyDir: {}
{{- if eq .Values.chiklets.mode "bundled" }}
- name: chiklets
  configMap:
    name: {{ include "foreman-selfservice.chikletConfigMapName" . }}
{{- else if eq .Values.chiklets.mode "existingConfigMap" }}
- name: chiklets
  configMap:
    name: {{ include "foreman-selfservice.chikletConfigMapName" . }}
{{- else if eq .Values.chiklets.mode "pvc" }}
- name: chiklets
  persistentVolumeClaim:
    claimName: {{ required "chiklets.existingClaim is required when chiklets.mode=pvc" .Values.chiklets.existingClaim }}
{{- end }}
{{- if .Values.foremanCa.existingConfigMap }}
- name: foreman-ca
  configMap:
    name: {{ .Values.foremanCa.existingConfigMap }}
    items:
      - key: {{ .Values.foremanCa.key }}
        path: foreman-ca.pem
{{- end }}
{{- with .Values.extraVolumes }}
{{ toYaml . }}
{{- end }}
{{- end }}
