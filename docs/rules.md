# Reglas del Torneo

## Mecanica del Juego

### Hex

Hex se juega en un tablero romboidal de 11x11 hexagonos (121 celdas). Dos jugadores se alternan colocando piedras:

- **Negro (Player 1)**: conecta el borde **superior** (fila 0) con el borde **inferior** (fila 10).
- **Blanco (Player 2)**: conecta el borde **izquierdo** (columna 0) con el borde **derecho** (columna 10).

Reglas basicas:
- No hay capturas — las piedras son permanentes.
- El primer jugador en conectar sus dos bordes gana.
- **No hay empates** en Hex (la geometria hexagonal lo garantiza).
- Cada celda tiene **6 vecinos**: `(-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0)`.

El espacio de estados de un tablero 11x11 es enorme — minimax puro es inviable. Necesitas MCTS, heuristicas, o tecnicas avanzadas.

### Variante Classic

Tablero vacio al inicio. **Informacion perfecta** — ambos jugadores ven todo el tablero en todo momento.

### Variante Dark (Fog of War)

Cada jugador **solo ve sus propias piedras** y las piedras del oponente que ha descubierto por **colision**. Introduce **informacion imperfecta**: debes razonar sobre lo que no puedes ver.

**Mecanica de colision:**
1. Intentas jugar en `(r, c)` que ya tiene una piedra oculta del oponente.
2. **Pierdes tu turno**, pero ahora puedes ver esa piedra.
3. `on_move_result(move, success)` te informa: `success=True` (se coloco) o `success=False` (colision).
4. `last_move` siempre es `None` en dark mode — no sabes donde jugo el oponente.

Tecnicas como determinizacion o Information Set MCTS (ISMCTS) son esenciales para dark mode.

## Formato del Torneo

### Liga round-robin

Todos contra todos (estudiantes + modelos de referencia) en **ambas variantes** (classic y dark).

- **4 partidas por par por variante** (2 como Negro, 2 como Blanco — balance de color perfecto).
- **Victoria = 1 punto, derrota = 0 puntos.**
- No hay empates en Hex.

### Dos ligas, standings combinados

- **Liga classic**: ranking por victorias en partidas classic.
- **Liga dark**: ranking por victorias en partidas dark.
- **Standings combinados**: puntos classic + puntos dark = puntos totales.

### Calificacion

Tu calificacion se basa en cuantos de los 6 modelos de referencia venciste en los standings combinados:

| Modelos vencidos | Calificacion |
|------------------|-------------|
| 0 | 0 |
| 1 | 5 |
| 2 | 6 |
| 3 | 7 |
| 4 | 8 |
| 5 | 9 |
| 6 | 10 |

- **"Vencer"** = tus puntos totales ≥ puntos totales del modelo. Empate favorece al estudiante.
- **Top 3** estudiantes por puntos totales obtienen automaticamente **10 puntos**.

Ver el README principal para un ejemplo completo de calificacion.

### Limite de movimientos

- **Classic**: 122 movimientos maximos.
- **Dark**: 363 movimientos maximos (las colisiones cuentan).
- Si se alcanza el limite, gana quien tenga menor **distancia Dijkstra** (shortest path distance) hacia su borde objetivo.

## Restricciones de Recursos

| Recurso | Limite | Detalle |
|---------|--------|---------|
| **Tiempo** | **15 segundos por jugada** | Estricto via `select()` + SIGKILL (no se puede evadir). Exceder = turno saltado. |
| **Memoria** | **8 GB** | Enforzado via Docker. |
| **CPUs** | **4 nucleos** | Compartidos con el referee y el oponente. |
| **Dependencias** | Solo `numpy` + stdlib | No instales ni importes nada mas. |
| **Aislamiento** | **Proceso separado** | Tu estrategia corre en su propio subproceso. No puedes acceder al motor del juego ni al oponente. |

### Reglas de turno

- Si excedes el timeout → **tu turno se salta** (no pierdes la partida, pero el oponente juega).
- Si tu estrategia crashea → **todos tus turnos restantes se saltan**.
- Si juegas en una celda invalida (ocupada o fuera de rango) → **tu turno se salta**.

**Nota:** El turno se salta, **no se pierde la partida**. El oponente simplemente juega de nuevo. Pero acumular turnos saltados te pone en gran desventaja.

### Presupuesto de tiempo

- `begin_game()` **no** consume tu presupuesto — solo se mide `play()`.
- 15 segundos por movimiento. Un juego de ~60 movimientos (~30 por jugador) = ~7.5 minutos maximo por partida.
- Tu estrategia se auto-compila con Cython al construir el Docker (para velocidad justa).

## Requisitos de la Estrategia

1. **Un solo archivo:** `estudiantes/<nombre_equipo>/strategy.py` — este es el **unico** archivo que el framework importa durante el torneo.
2. **Clase:** Debe ser subclase de `Strategy` de `strategy.py`.
3. **Nombre unico:** La propiedad `name` debe ser unica entre todos los equipos (convencion: `"NombreEstrategia_nombreequipo"`).
4. **Ambas variantes:** Debe funcionar para `classic` y `dark` (fog of war).
5. **Interfaz:** Usa unicamente `begin_game(config)`, `play(board, last_move)`, y `on_move_result(move, success)`.
6. **Todo en un archivo:** Si necesitas funciones auxiliares, defínelas dentro de `strategy.py`. Otros archivos en tu directorio no seran accesibles durante la evaluacion.
7. **README obligatorio:** `estudiantes/<nombre_equipo>/README.md` debe documentar tu algoritmo, manejo de dark mode, decisiones de diseno, y resultados de pruebas.

## Enfoques Prohibidos

- **No aprendizaje automatico** (redes neuronales, optimizacion basada en gradientes, modelos aprendidos).
- **No aprendizaje por refuerzo** (Q-learning, policy gradient, etc.).
- **Permitido:** MCTS, minimax, heuristicas, simulaciones, busqueda, teoria de la informacion, tablas precomputadas, agentes basados en utilidad.

La intencion es que las estrategias utilicen razonamiento algoritmico, no parametros aprendidos.

## Criterios de Descalificacion

Una estrategia puede ser descalificada si:

- Falla consistentemente (excepciones no manejadas en la mayoria de los juegos).
- Excede el limite de tiempo en la mayoria de los juegos.
- Usa dependencias externas mas alla de `numpy` + biblioteca estandar.
- Intenta acceder al motor del juego, al estado del oponente, o a informacion que no le corresponde.
- Utiliza tecnicas de ML/RL (redes neuronales, aprendizaje por refuerzo).
- Modifica archivos o estado del sistema fuera del directorio de su equipo.
- Intenta evadir el timeout o el aislamiento de procesos.
- Intenta comunicarse con otros procesos o acceder a la red.

## Juego Limpio

- Tu estrategia corre en un **proceso separado**, completamente aislado del motor del juego, del referee y del oponente. No hay forma de acceder a informacion privilegiada.
- Todas las estrategias reciben la **misma configuracion**: mismo tamano de tablero, mismas reglas, mismo timeout.
- Las semillas aleatorias del torneo se generan en tiempo de ejecucion y no se comparten con los equipos.
- Tu estrategia se **auto-compila con Cython** al construir el contenedor Docker, asegurando una comparacion de velocidad justa entre todos los equipos.
- El timeout se enforza via `select()` + `SIGKILL` desde un proceso separado — es **imposible** de evadir desde dentro de tu estrategia (no puedes atrapar SIGKILL, no puedes deshabilitar el timer).
