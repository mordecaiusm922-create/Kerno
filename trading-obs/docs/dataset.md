# Dataset abierto y ruta de coste cero

## Qué es

Todos los días, GitHub Actions (gratis en repos públicos) hace esto:

1. **Descarga** los trades del día D-2 de los archivos públicos de Binance (spot y perpetuo USDT-M) y Bybit (perpetuo), y verifica el SHA-256 que publica Binance.
2. **Procesa** esos trades con el mismo motor de Kerno: eventos con features point-in-time y su resultado a 10 s y 30 s, entrando 250 ms después.
3. **Publica** en Hugging Face:
   - los eventos;
   - un resumen diario;
   - el basis spot/perp por minuto;
   - un manifiesto con los hashes de fuentes y salidas, la versión del código y los parámetros.

No hace falta servidor, base de datos, tu laptop ni dinero.

```bash
kerno dataset build --date 2026-09-20      # un día
kerno dataset build --start 2026-09-01 --end 2026-09-20
kerno dataset publish --repo <usuario-hf>/kerno-microstructure
```

## Garantías (probadas en `tests/test_dataset.py`)

- **Mismo resultado que el pipeline completo.** Procesar un día aislado da exactamente los mismos eventos, features y resultados que meter todo el histórico en la base de datos y correr el motor continuo más el validador. La razón: el estado del motor depende solo de los últimos 5 minutos, y se calientan 10.
- **Determinista.** Dos builds del mismo día producen archivos con el mismo SHA-256, siempre que se usen las mismas versiones de dependencias (`requirements.txt`).
- **Fuentes verificadas.** Un checksum que no coincide aborta el proceso y descarta el archivo.
- **Los trades crudos no se republican**, solo datos derivados (ver "Legal").

## Activarlo (unos 10 minutos, todo gratis)

1. Crea una cuenta en huggingface.co. No pide tarjeta.
2. Ve a **Settings → Access Tokens → New token**, tipo *Write*, y cópialo.
3. En GitHub, en tu repo, ve a **Settings → Secrets and variables → Actions**:
   - en *Secrets*, crea `HF_TOKEN` con el token;
   - en *Variables*, crea `HF_DATASET_REPO` con `tu-usuario-hf/kerno-microstructure`.
4. Ve a **Actions → daily-dataset → Run workflow**. Deja las fechas vacías (así procesa el día de hace dos) o pon un rango para cargar histórico (máximo 31 días por corrida).
5. Revisa el log:
   - Si dice `HTTP 451/403 (geo-blocked…)`, los runners de GitHub (EE. UU.) no pueden descargar de esa fuente. Quita esa fuente con `--sources` o avísame para buscar alternativa.
   - Si no configuras Hugging Face, el dataset queda igual como *artifact* descargable durante 7 días.

Desde entonces corre solo cada día.

## Negocio: de gratis a de pago, paso a paso

**Qué vendes:** datos derivados y verificables, no recomendaciones.

| Etapa | Qué | Coste | Señal para avanzar |
|---|---|---|---|
| 1. Credibilidad | Dataset público en HF (CC BY-NC 4.0), código abierto, auditoría publicada | 0 | Descargas, likes, issues y preguntas |
| 2. Audiencia | Una nota corta semanal con lo que dicen los datos (p. ej. "tasa de continuación de spikes en BTC perp vs spot") en X, LinkedIn o Substack | 0 | Gente que pide datos más frescos, más símbolos o uso comercial |
| 3. Primer ingreso | Licencia comercial del dataset y/o API de pago en **RapidAPI** (ellos cobran, gestionan keys y se quedan una comisión; tú no pagas fijo) | 0 fijo | 3–5 clientes pagando |
| 4. Tiempo real | Servidor 24/7 (Oracle Always Free, o 5 €/mes) con el stack completo de Kerno | 0–5 €/mes | Ingresos que lo cubran |

**La licencia es tu palanca.** CC BY-NC permite a investigadores y estudiantes usarlo gratis, lo que te da difusión. Cualquier fondo, bot comercial o empresa necesita una licencia comercial. Así compiten Kaiko o Tardis, pero tú entras por abajo y con verificabilidad como diferenciador.

**Tu ventaja frente a los grandes:**
- **Reproducibilidad pública.** Nadie más publica el hash de fuente → código → salida.
- **Etiquetas listas para ML sin fuga de datos futuros.**
- **Precio de entrada bajo.**

No compites en latencia ni en cobertura.

## Legal (orientación, no asesoría)

- **Datos derivados**, no trades crudos: es el menor riesgo razonable. Lee igualmente los términos de uso de datos de Binance y Bybit antes de cobrar.
- **Nada de lenguaje de recomendación** ("compra", "vende", "señal ganadora"). El dataset lo aclara en su ficha.
- **La licencia CC BY-NC 4.0** de la ficha (`kerno/dataset_card.md`) es una propuesta; cámbiala si prefieres otra.
- **El código del repo no tiene licencia todavía**, así que legalmente es "todos los derechos reservados" aunque sea público. Decide si quieres MIT o Apache-2.0 (abierto, más difusión) o mantenerlo así.
