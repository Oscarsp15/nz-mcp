# Playbook — Modificar `sql_guard.py`

> **Alta sensibilidad.** Lee primero [security-model.md](../architecture/security-model.md) y [security-engineer.md](../roles/security-engineer.md) **completos**.
> Cualquier cambio que **reduce estrictez** requiere ADR + aprobación humana explícita.

## Cuándo modificar `sql_guard`

Razones legítimas:
- Añadir un statement kind nuevo soportado (ej. `MERGE`).
- Cubrir un bypass adversarial encontrado (siempre añade, nunca quita).
- Mejorar mensajes de error / hints.
- Refactor sin cambio de comportamiento (cobertura debe mantenerse 100 %).

Razones ilegítimas:
- "El usuario se queja del falso positivo X" → prefiere ajustar la tool, no el guard.
- "Solo este tipo de DELETE es seguro" → no.
- "Es feo el código actual" → solo si tests cubren todo.

## Pasos

### 1. Documentar la motivación

- Si **aumenta** estrictez: nota en PR + ADR si es estructural.
- Si **reduce** estrictez: ADR obligatorio + aprobación humana citada en el PR.

### 2. Añadir tests adversariales **antes** del cambio

- Edita `tests/unit/test_sql_guard_adversarial.py`.
- Añade ≥ 3 casos representativos del bypass o del nuevo soporte.
- Corre el test → debe **fallar** (red).

### 3. Implementar el cambio

- Editar `src/nz_mcp/sql_guard.py`.
- Mantener clasificación basada en `sqlglot.parse(sql, read="postgres")`.
- Mantener rechazo de stacked statements (`len(parsed) > 1`).
- Mantener rechazo de `UPDATE`/`DELETE` sin `WHERE`.
- Cubrir el caso nuevo.

### 4. Verificar tests verdes

- Tests adversariales nuevos → green.
- Tests existentes → siguen green.
- Cobertura `sql_guard.py` = 100 % (no negociable).

### 5. Actualizar [security-model.md](../architecture/security-model.md)

- Si añadiste statement kind: añadir fila a la matriz de reglas por modo.
- Si descubriste vector de ataque: añadir a la lista de casos adversariales.

### 6. Auditoría

- Pasar [pr-audit.md](../standards/pr-audit.md), prestando atención extra a la dimensión Seguridad.
- El **auditor** debe ser distinto al autor — sin excepción para este archivo.

## Reglas de oro

1. **Nunca whitelist por regex.** Parser, no patterns.
2. **Default deny.** Statement no reconocido → reject.
3. **No comentarios "TODO" en `sql_guard`** sin issue asociado.
4. **Si dudas, rechaza.** Falsos positivos son aceptables; falsos negativos no.

## Anti-patrones (rechazo automático)

- ❌ `re.search` para detectar SQL.
- ❌ Permitir `;` adicionales aunque "no contengan nada peligroso".
- ❌ Reducir estrictez sin ADR.
- ❌ Mover la validación a otro módulo "más conveniente".
- ❌ Caché del resultado de `validate()` (cada llamada vuelve a parsear).

## Plantilla de ADR (si reduce estrictez)

```markdown
# ADR NNNN — Permitir <statement/case> en sql_guard

## Contexto
<por qué la estrictez actual molesta>

## Decisión
Permitir <case> bajo modo <X>, manteniendo rechazo bajo modos inferiores.

## Alternativas consideradas
- Mantener estrictez actual: <coste>
- Mover la responsabilidad al usuario Netezza: <por qué no basta>

## Consecuencias
- Positivas: <UX, cobertura de casos legítimos>
- Negativas: <ampliación de superficie>
- Mitigaciones: tests adversariales nuevos, monitorización en logs

## Aprobación humana
Aprobado por @Oscarsp15 en <fecha> tras revisión de <evidencia>.
```
