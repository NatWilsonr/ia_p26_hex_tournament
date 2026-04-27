# PaN — Estrategia para Hex


## Descripción general

Nuestra estrategia para el torneo de Hex está basada en **Monte Carlo Tree Search (MCTS)**, adaptada para las dos variantes del juego:

- **classic**: información perfecta
- **dark**: información imperfecta

La implementación está hecha completamente en `strategy.py`, sin redes neuronales, y pensada para funcionar dentro del límite de **15 segundos por jugada**.

---

## Idea principal

La base del agente es **MCTS**, con sus cuatro etapas clásicas:

1. **Selection**
2. **Expansion**
3. **Rollout / Simulation**
4. **Backpropagation**

Sobre esta base, la estrategia se ajusta según la variante del juego.

---

## Variante classic

Para la variante **classic** usamos **UCT + RAVE**.

### UCT
UCT se usa para balancear exploración y explotación en el árbol de búsqueda.

### RAVE
RAVE (**Rapid Action Value Estimation**) ayuda a acelerar la convergencia, especialmente en etapas tempranas de la partida. La idea es combinar:

- estadísticas normales del nodo
- estadísticas derivadas de acciones observadas en rollouts

Esto ayuda a estimar más rápido qué movimientos son prometedores cuando aún no hay suficientes visitas en el árbol.

---

## Variante dark

Para la variante **dark** usamos **Multiple Determinization MCTS (MD-MCTS)**.

Como no se conoce por completo el estado del rival, generamos varias posibles versiones del tablero que sean consistentes con la información disponible. Sobre cada una de esas determinizaciones se ejecuta MCTS, y luego las decisiones se agregan por votación.

Esto permite adaptar MCTS a un entorno de información imperfecta sin rediseñar por completo el algoritmo.

---

## Heurísticas ligeras

Además del MCTS base, usamos algunas heurísticas de bajo costo computacional:

### Movimientos relevantes
Se priorizan movimientos cercanos a fichas ya colocadas para reducir el espacio de búsqueda.

### Respuestas a puentes
Durante los rollouts se consideran respuestas simples a patrones de puente.

### Apertura guiada
En el early game se favorecen aperturas razonables para evitar jugadas débiles al inicio.

### Prioridad táctica
Seguimos la prioridad:

**ganar > bloquear**

Si existe una jugada ganadora inmediata, se toma. Si no, se consideran bloqueos importantes al rival.

---

## Objetivo de diseño

La estrategia fue diseñada buscando:

- buen desempeño en **classic**
- robustez en **dark**
- eficiencia computacional
- compatibilidad total con el framework del torneo
- mantener una implementación contenida en un solo archivo

---

## Tradeoff importante

Uno de los principales retos del diseño fue balancear:

- simulaciones más “inteligentes”
- contra mayor número total de simulaciones

Agregar demasiada lógica al rollout o al proceso de determinization puede hacer que cada simulación sea más cara, lo cual reduce el número total de iteraciones de MCTS dentro del tiempo permitido.

---

## Posibles cuellos de botella identificados

Durante el análisis del agente, identificamos estos puntos delicados:

- **rollouts demasiado complejos**, que pueden reducir el número de simulaciones
- **RAVE en etapas tardías**, donde podría introducir ruido si sigue teniendo demasiado peso
- **determinization costosa en dark**, si se generan demasiados escenarios o muy caros de evaluar

---

## Estado actual

La estrategia actual ya cuenta con:

- MCTS funcional
- UCT + RAVE en **classic**
- MD-MCTS en **dark**
- heurísticas ligeras de selección y rollout

Con esta base se logró una estrategia funcional y competitiva. Las siguientes mejoras probables serían ajustes finos de eficiencia, no rediseños completos.

---