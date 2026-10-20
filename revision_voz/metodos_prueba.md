# Métodos gratuitos para probar la voz (se amplía en cada revisión semanal)

| Método | Qué mide | Cómo | Desde |
|---|---|---|---|
| Whisper small (sherpa-onnx, local) | Si se entiende cada palabra: nombres, siglas, inglés, cifras | revisar.py: audio real del Short vs guion | 20/10/2026 |
| Prueba de variantes con Whisper | Cuál de varias pronunciaciones se entiende mejor (8–16 tomas cada una) | laboratorio de palabras (ver LEEME) | 15/10/2026 |
| DNSMOS (Microsoft, local, gratis) | Calidad de la voz 1–5: SIG (voz limpia y natural), BAK (fondo, ruido, zumbidos), OVRL y P808 (nota global) | python3 dnsmos.py audio.mp3 (modelos en dnsmos/; necesita librosa) | 20/10/2026 |

Ideas para próximas semanas: otro ASR para tener dos «oídos» (p. ej. Paraformer o Whisper medium de sherpa-onnx), medir
velocidad en sílabas por segundo y pausas entre frases, y un detector de entonación plana (variación de tono por frase).
