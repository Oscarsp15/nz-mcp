# ADR 0004 — Integration tests solo locales en v0.1

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: QA Engineer + Release Engineer (IA) + validación humana

## Contexto

La instancia Netezza de referencia está **on-premise** y solo es accesible vía VPN corporativa. GitHub Actions runners (cloud) no pueden alcanzarla. Necesitamos decidir cómo correr `@pytest.mark.integration` en CI sin sacrificar señal.

Opciones:

1. **Skip en CI**: integration tests solo locales por desarrollador.
2. **Self-hosted runner**: máquina dentro de la red corporativa registrada como runner.
3. **Imagen Docker de Netezza**: IBM no la publica oficialmente. Descartado.
4. **Mock de alta fidelidad**: caro de mantener, baja confianza.

## Decisión

Para **v0.1**:
- CI corre **solo** unit + contract + adversarial + property con mocks (`pytest -m "not integration"`).
- Integration tests se corren **locales** por el desarrollador antes de cada release, con VPN.
- El proceso de release ([release.md](../actions/release.md)) requiere que el humano confirme explícitamente que los integration tests pasaron.

Para **v0.2+**:
- Evaluar self-hosted runner registrado en la red corporativa (ADR nuevo).

## Alternativas consideradas

1. **Self-hosted desde día 1**: requiere mantener una máquina prendida y actualizada; sobreingeniería para v0.1 con un solo dev/owner.
2. **Mock testcontainer "fake-netezza"**: ningún proyecto OSS conocido lo implementa; construirlo nosotros nos distrae del MVP.
3. **Tests integration omitidos del repo**: pierdes la regresión y dependes 100 % del juicio humano. Rechazado.

## Consecuencias

- ✅ CI rápido, sin secretos de Netezza en GitHub.
- ✅ Confianza alta porque hay integration tests, aunque corran fuera de CI.
- ⚠️ Riesgo: alguien hace release sin haberlos corrido. Mitigado por checklist obligatorio en `release.md`.
- ⚠️ Contributors externos no pueden correr integration sin acceso a Netezza. Aceptable: PRs externos cubren unit/contract; integration es responsabilidad del maintainer.

## Monitorizar

- Frecuencia de bugs detectados solo en integration → si crece, acelerar self-hosted.
- Releases que necesitaron hotfix por bug que un integration habría detectado → trigger directo para v0.2.
