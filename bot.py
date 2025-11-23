import os
import json
from datetime import datetime, timedelta, time as dtime

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from openai import OpenAI

# ==========================
#   CARGA VARIABLES
# ==========================

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
#   ARCHIVOS
# ==========================

PREMIUM_FILE = "premium_users.json"
USERS_FILE = "usuarios.json"
XP_FILE = "xp_users.json"
REF_FILE = "referrals.json"

# ==========================
#   HELPERS JSON
# ==========================


def cargar_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def guardar_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def cargar_premium():
    return cargar_json(PREMIUM_FILE, {})


def guardar_premium(data: dict):
    guardar_json(PREMIUM_FILE, data)


def cargar_usuarios():
    return cargar_json(USERS_FILE, [])


def guardar_usuarios(lista):
    guardar_json(USERS_FILE, lista)


def cargar_xp():
    return cargar_json(XP_FILE, {})


def guardar_xp(data):
    guardar_json(XP_FILE, data)


def cargar_ref():
    return cargar_json(REF_FILE, {})


def guardar_ref(data):
    guardar_json(REF_FILE, data)


# ==========================
#   USUARIOS / XP
# ==========================


def registrar_usuario(user_id: int):
    usuarios = cargar_usuarios()
    if user_id not in usuarios:
        usuarios.append(user_id)
        guardar_usuarios(usuarios)


def add_xp(user_id: int, amount: int):
    data = cargar_xp()
    uid = str(user_id)
    data[uid] = data.get(uid, 0) + amount
    guardar_xp(data)


def get_level(xp: int) -> int:
    if xp < 20:
        return 1
    if xp < 50:
        return 2
    if xp < 100:
        return 3
    if xp < 200:
        return 4
    if xp < 350:
        return 5
    if xp < 600:
        return 6
    if xp < 1000:
        return 7
    return 8


def level_name(level: int) -> str:
    mapping = {
        1: "Casual",
        2: "Principiante",
        3: "Intermedio",
        4: "Competitivo",
        5: "Pre-PRO",
        6: "PRO",
        7: "Elite FNCS",
        8: "GOD-Tier",
    }
    return mapping.get(level, "Sin nivel")


# ==========================
#   SISTEMA PREMIUM
# ==========================


def vencio_premium(fecha_str: str) -> bool:
    if not fecha_str:
        return False
    fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
    return fecha < datetime.now()


def es_premium(user_id: int) -> bool:
    premium = cargar_premium()
    uid = str(user_id)
    if uid not in premium:
        return False

    entry = premium[uid]

    # Formato viejo
    if isinstance(entry, str):
        return not vencio_premium(entry)

    # Lifetime
    if entry.get("lifetime"):
        return True

    exp = entry.get("exp")
    if not exp:
        return False

    return not vencio_premium(exp)


def es_premium_plus(user_id: int) -> bool:
    premium = cargar_premium()
    uid = str(user_id)
    if uid not in premium:
        return False
    entry = premium[uid]
    if isinstance(entry, str):
        return False
    return entry.get("plan") == "plus"


def obtener_info_premium(user_id: int) -> str:
    premium = cargar_premium()
    uid = str(user_id)
    if uid not in premium:
        return "No sos Premium."

    entry = premium[uid]
    plan = "Standard"

    # Formato viejo
    if isinstance(entry, str):
        exp = entry
    else:
        plan = entry.get("plan", "Standard")
        if entry.get("lifetime"):
            return f"Premium {plan} de por vida 🏆"
        exp = entry.get("exp")

    return f"Premium {plan} activo hasta: {exp}"


def add_days_premium(user_id: int, dias: int, plan: str = "standard"):
    premium = cargar_premium()
    uid = str(user_id)

    entry = premium.get(uid)

    # Si ya es de por vida, no tocar
    if isinstance(entry, dict) and entry.get("lifetime"):
        return

    if entry is None:
        # Crear nuevo
        exp = datetime.now() + timedelta(days=dias)
        premium[uid] = {
            "lifetime": False,
            "exp": exp.strftime("%Y-%m-%d"),
            "plan": plan,
        }
    else:
        # Extender
        if isinstance(entry, str):
            base = datetime.strptime(entry, "%Y-%m-%d")
            new_exp = base + timedelta(days=dias)
            premium[uid] = {
                "lifetime": False,
                "exp": new_exp.strftime("%Y-%m-%d"),
                "plan": plan,
            }
        else:
            exp_str = entry.get("exp")
            if exp_str:
                base = datetime.strptime(exp_str, "%Y-%m-%d")
            else:
                base = datetime.now()
            new_exp = base + timedelta(days=dias)
            entry["exp"] = new_exp.strftime("%Y-%m-%d")
            # si ya era plus, mantener
            if entry.get("plan") is None:
                entry["plan"] = plan
            premium[uid] = entry

    guardar_premium(premium)


# ==========================
#   DESCUENTO MENSUAL
# ==========================

DESCUENTO_MENSUAL = {
    "activo": False,
    "codigo": "FNCS50",
    "porcentaje": 0.50,  # 50% al plan mensual
    "expira": None,
}


def descuento_mensual_activo():
    if not DESCUENTO_MENSUAL["activo"]:
        return False

    exp = datetime.strptime(DESCUENTO_MENSUAL["expira"], "%Y-%m-%d %H:%M")
    if datetime.now() > exp:
        DESCUENTO_MENSUAL["activo"] = False
        return False

    return True


# ==========================
#   REFERIDOS
# ==========================


def registrar_referido(user_id: int, ref_id: int) -> str:
    """Registra que user_id usó el código de ref_id."""
    if user_id == ref_id:
        return "No podés usar tu propio código."

    refs = cargar_ref()
    u = str(user_id)
    r = str(ref_id)

    info_u = refs.get(u, {"ref_by": None, "referred": [], "premios": []})

    if info_u.get("ref_by"):
        return "Ya usaste un código de referido antes."

    # Asignar
    info_u["ref_by"] = r
    refs[u] = info_u

    info_r = refs.get(r, {"ref_by": None, "referred": [], "premios": []})
    if u not in info_r["referred"]:
        info_r["referred"].append(u)
    refs[r] = info_r

    guardar_ref(refs)
    return "✅ Código de referido aplicado correctamente."


def procesar_bonus_referido(uid_str: str):
    """
    Cuando un usuario uid_str se activa Premium,
    si tiene ref_by y el bonus no fue usado, darle 7 días al referrer.
    """
    refs = cargar_ref()
    if uid_str not in refs:
        return

    data_u = refs[uid_str]
    ref_by = data_u.get("ref_by")
    if not ref_by:
        return

    # Marcar que este usuario ya otorgó bonus a su referrer
    data_r = refs.get(ref_by, {"ref_by": None, "referred": [], "premios": []})
    premios = data_r.get("premios", [])

    if uid_str in premios:
        # Ya se le dio bonus por este usuario
        return

    # Dar 7 días de premium standard al referrer
    add_days_premium(int(ref_by), 7, plan="standard")

    premios.append(uid_str)
    data_r["premios"] = premios
    refs[ref_by] = data_r
    guardar_ref(refs)


# ==========================
#   BASE DE SENS DE PRO PLAYERS
# ==========================

PRO_SENS = {
    "clix": {
        "display": "Clix",
        "aliases": ["clix"],
        "dpi": 800,
        "x": 8.7,
        "y": 6.3,
        "target": 90.9,
        "scope": 82.7,
        "estilo": "Muy agresivo, muchos piques explosivos y edición rápida."
    },
    "bugha": {
        "display": "Bugha",
        "aliases": ["bugha", "buga"],
        "dpi": 800,
        "x": 6.4,
        "y": 6.4,
        "target": 45,
        "scope": 45,
        "estilo": "Equilibrado y súper consistente, casi sin errores mecánicos."
    },
    "tayson": {
        "display": "TaySon",
        "aliases": ["tayson", "tay son"],
        "dpi": 800,
        "x": 5.8,
        "y": 5.8,
        "target": 29,
        "scope": 30,
        "estilo": "AIM muy preciso, juega perfecto mid/late game."
    },
    "epikwhale": {
        "display": "EpikWhale",
        "aliases": ["epikwhale", "epik whale", "epik"],
        "dpi": 800,
        "x": 7.0,
        "y": 7.0,
        "target": 30,
        "scope": 40,
        "estilo": "Mix agresivo + estratégico, mucho control de piezas."
    },
    "veno": {
        "display": "Veno",
        "aliases": ["veno"],
        "dpi": 800,
        "x": 5.8,
        "y": 5.8,
        "target": 45,
        "scope": 45,
        "estilo": "Agresivo inteligente, busca ángulos y trades seguros."
    },
    "mrsavage": {
        "display": "MrSavage",
        "aliases": ["mrsavage", "mr savage"],
        "dpi": 1450,
        "x": 6.3,
        "y": 6.3,
        "target": 50,
        "scope": 55,
        "estilo": "Ultra agresivo, confía en sus mecánicas y edits rápidos."
    },
    "peterbot": {
        "display": "Peterbot",
        "aliases": ["peterbot", "peter bot"],
        "dpi": 1600,
        "x": 4.6,
        "y": 4.6,
        "target": 45,
        "scope": 45,
        "estilo": "AIM enfermizo, juega muy agresivo pero con buen tracking."
    },
    "pollo": {
        "display": "Pollo",
        "aliases": ["pollo"],
        "dpi": 800,
        "x": 6.5,
        "y": 6.5,
        "target": 50,
        "scope": 50,
        "estilo": "Juega agresivo pero ordenado, muy bueno en box fights."
    },
}


def obtener_sens_pro_desde_texto(texto: str):
    """
    Busca dentro del mensaje si aparece el nombre de algún pro
    y devuelve un mensaje con su sens exacta.
    """
    low = texto.lower()

    for key, data in PRO_SENS.items():
        for alias in data["aliases"]:
            if alias in low:
                return (
                    f"🎮 *Sens de {data['display']}*\n\n"
                    f"• DPI: *{data['dpi']}*\n"
                    f"• X: *{data['x']}%*\n"
                    f"• Y: *{data['y']}%*\n"
                    f"• Targeting: *{data['target']}%*\n"
                    f"• Scope: *{data['scope']}%*\n\n"
                    f"🧠 Estilo de juego: {data['estilo']}\n\n"
                    "Recordá que estas sens pueden cambiar con el tiempo.\n"
                    "Si querés, te armo una *sens personalizada* basada en esta pero "
                    "ajustada a tu DPI, resolución y estilo (agresivo/pasivo)."
                )

    return None
# ==========================
#   MENÚ / SECCIONES
# ==========================


def get_menu():
    text = (
        "📋 *MENÚ PRINCIPAL – COACH FORTNITE IA PREMIUM*\n\n"
        "Elegí una categoría o mandame un mensaje.\n\n"
        "🔥 Todos los PROS me prefieren.\n"
        "🔥 Miles de jugadores ya entrenaron conmigo.\n"
        "🔥 ¿Querés sacar earnings? Yo te guío paso a paso.\n"
    )

    kb = [
        [
            InlineKeyboardButton("🎛 Config & Sens", callback_data="cfg"),
            InlineKeyboardButton("🎯 AIM / Mecánicas", callback_data="sens"),
        ],
        [
            InlineKeyboardButton("📚 Rutinas (PREMIUM)", callback_data="entreno"),
            InlineKeyboardButton("🗺 Drops competitivos (PREMIUM)", callback_data="mapas"),
        ],
        [
            InlineKeyboardButton("🔫 Combos META", callback_data="combos"),
            InlineKeyboardButton("⚙ Optimizar PC (PREMIUM)", callback_data="optimizar"),
        ],
        [
            InlineKeyboardButton("👥 Duo / Comms", callback_data="duo"),
            InlineKeyboardButton("🧠 Mentalidad", callback_data="mento"),
        ],
        [InlineKeyboardButton("🏷 Rol competitivo (PREMIUM)", callback_data="rol")],
        [
            InlineKeyboardButton("📊 Analizar nivel (PREMIUM)", callback_data="analizar"),
            InlineKeyboardButton("📝 Analizar partida (PREMIUM)", callback_data="resumen"),
        ],
        [
            InlineKeyboardButton("💎 VER PREMIUM", callback_data="buy_premium"),
        ],
    ]

    return text, InlineKeyboardMarkup(kb)


def text_section(data: str) -> str:
    sections = {
        "cfg": (
            "🎮 *CONFIGURACIÓN Y SENSIBILIDAD PRO*\n\n"
            "Mandame:\n"
            "• DPI\n"
            "• Resolución\n"
            "• Si sos más *agresivo* o *pasivo*\n\n"
            "Y te armo una config estilo *Clix / Peterbot / Queasy* según tu estilo.\n"
            "Si querés algo tipo un pro específico, decime por ejemplo: *\"sens tipo Clix\"*."
        ),
        "sens": (
            "🎯 *AIM / MECÁNICAS / EDICIÓN*\n\n"
            "Mapas recomendados:\n"
            "• Raider464 Aim Trainer\n"
            "• Skavook Aim\n"
            "• Piece Control / Realistics 1v1\n\n"
            "Decime tu nivel (bajo / medio / alto) y cuánto podés entrenar por día "
            "y te hago una rutina de AIM / edición adaptada."
        ),
        "entreno": (
            "📚 *RUTINAS DE ENTRENAMIENTO PRO (PREMIUM)*\n\n"
            "Con Premium recibís *rutinas DIARIAS* armadas como las de jugadores FNCS:\n"
            "• Warmup de AIM\n"
            "• Mecánicas y piece control\n"
            "• Realistics / Arena / Scrims\n"
            "• Trabajo específico según tus errores\n\n"
            "Decime si tenés 15 / 30 / 60 minutos y tu objetivo (FNCS, Cash Cups, Ranked)."
        ),
        "mapas": (
            "🗺 *DROPS COMPETITIVOS & ROTACIONES (PREMIUM)*\n\n"
            "Con Premium te recomiendo:\n"
            "• Drops con loot consistente\n"
            "• Rotaciones limpias sin quedar en medio\n"
            "• Spots para mid / late game\n"
            "• Plan de partida según si jugás solo / duo / trío\n\n"
            "Decime modo, región y si jugás agresivo o más macro."
        ),
        "combos": (
            "🔫 *COMBOS META (GENERALES)*\n\n"
            "Depende de la season, pero en general:\n"
            "• Escopeta + AR + Heals\n"
            "• Escopeta + SMG + Heals\n"
            "• Si sos IGL: priorizá movilidad y curas.\n\n"
            "Decime la season actual y te ajusto los combos a lo que está fuerte ahora."
        ),
        "optimizar": (
            "⚙ *OPTIMIZACIÓN DE PC PARA FORTNITE (PREMIUM)*\n\n"
            "Mandame tu:\n"
            "• CPU\n"
            "• GPU\n"
            "• RAM\n"
            "• Hz del monitor\n\n"
            "Y te doy una configuración exacta para más FPS y menos input lag."
        ),
        "duo": (
            "👥 *DUO / COMMS / ROLES*\n\n"
            "Contame cómo juegan vos y tu duo:\n"
            "• Quién edita mejor\n"
            "• Quién se tiltea más\n"
            "• Quién mira más el mapa\n\n"
            "Y te digo quién debería ser IGL / Fragger / Support y cómo mejorar sus calls."
        ),
        "mento": (
            "🧠 *MENTALIDAD COMPETITIVA*\n\n"
            "Decime qué te frustra más (ping, errores tontos, nervios en torneo, etc.) "
            "y te doy tips concretos para:\n"
            "• No tiltearte\n"
            "• Jugar más frío en endgame\n"
            "• Resetearte entre partidas\n"
            "• Tener una rutina previa a torneo."
        ),
        "rol": (
            "🏷 *ROL COMPETITIVO (PREMIUM)*\n\n"
            "Contame tu estilo:\n"
            "• ¿Sos más agresivo o macro?\n"
            "• ¿Editás rápido?\n"
            "• ¿Te gusta tomar decisiones?\n\n"
            "Y te digo qué rol te encaja mejor (IGL / Fragger / Support) y cómo jugarlo."
        ),
        "analizar": (
            "📊 *ANÁLISIS DE NIVEL (PREMIUM)*\n\n"
            "Mandame:\n"
            "• Plataforma (PC/Consola)\n"
            "• FPS promedio\n"
            "• División / rango actual\n"
            "• Si jugás más creativo o arena\n\n"
            "Y te digo en qué estás fuerte, en qué flojo y qué entrenar primero."
        ),
        "resumen": (
            "📝 *ANÁLISIS DE PARTIDA (PREMIUM)*\n\n"
            "Mandame un resumen de tu partida:\n"
            "• Dónde caíste\n"
            "• Qué loot tenías\n"
            "• En qué fase moriste (early / mid / late)\n"
            "• Cómo te mató el rival\n\n"
            "Y te explico qué podrías haber hecho distinto y cómo jugar esa situación como un PRO."
        ),
    }

    return sections.get(data, "❓ Sección no encontrada.")


# ==========================
#   COMANDOS BÁSICOS
# ==========================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    registrar_usuario(user_id)

    texto = (
        "👋 *Bienvenido al Coach de Fortnite IA* – el bot más elegido por los PROS y miles de jugadores. 🔥\n\n"
        "💸 *¿Querés empezar a sacar earnings en torneos?* Yo te guío paso a paso.\n\n"
        "Te ayudo con TODO lo que necesitás:\n"
        "🎮 Configuración y Sensibilidad PRO\n"
        "🎯 AIM / Mecánicas / Edición\n"
        "🗺 Rotaciones y Drops competitivos\n"
        "⚙ Optimización de PC para más FPS\n"
        "📚 Rutinas de entrenamiento diarias\n"
        "🧠 Mentalidad competitiva\n"
        "🔫 Combos META\n"
        "📈 Análisis de estilo de juego y partidas\n\n"
        "📌 *Comandos principales:*\n"
        "• /menu – Menú principal con botones\n"
        "• /config – Ayuda con configuración y sens\n"
        "• /sens – Rutina de AIM / mecánicas\n"
        "• /entrenamiento – Rutinas diarias (PREMIUM)\n"
        "• /mapas – Drops competitivos (PREMIUM)\n"
        "• /combos – Armas META\n"
        "• /optimizar – Optimizar tu PC (PREMIUM)\n"
        "• /rol – Rol competitivo (PREMIUM)\n"
        "• /analizar – Analizo tu nivel (PREMIUM)\n"
        "• /resumen – Analizo tu partida (PREMIUM)\n"
        "• /premiuminfo – Cómo pagar y planes\n"
        "• /perfil – Tu XP, nivel y estado Premium\n"
        "• /referidos – Tu código para invitar amigos\n"
        "• /replay – Cómo mandarme info de un replay\n\n"
        "🎮 *Sensibilidades de PROS*\n"
        "Pedime cosas como: _\"sens tipo Clix\"_, _\"sens tipo Peterbot\"_, "
        "_\"sens de Queasy\"_ y te explico el estilo y te ajusto una sens inspirada en ellos.\n\n"
        "💎 *Planes Premium:*\n"
        "• 5 USD → 30 días\n"
        "• 15 USD → para siempre (lifetime 🏆)\n"
        "Después de pagar, mandá la *captura del pago* 📸 y el admin te activa.\n\n"
        "🔥 Estoy listo para llevarte al siguiente nivel competitivo.\n"
        "Usá /menu o escribime qué querés mejorar. 👇"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /help muestra lo mismo que /start
    await start(update, context)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    registrar_usuario(user_id)

    text, kb = get_menu()
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Coach Fortnite IA Premium*\n\n"
        "Bot diseñado para jugadores que quieren competir en serio: FNCS, Cash Cups, scrims y ranked.\n"
        "Uso IA para analizar tu juego y armarte un plan de mejora realista, no humo.",
        parse_mode="Markdown",
    )


async def premiuminfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "💎 *PREMIUM FORTNITE COACH IA*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Con Premium desbloqueás:\n"
        "✔ IA PRO ilimitada (me podés preguntar lo que sea de Fortnite)\n"
        "✔ Rutinas diarias de entrenamiento\n"
        "✔ Drops competitivos y rotaciones\n"
        "✔ Optimización de PC\n"
        "✔ Análisis de partidas y de tu nivel\n"
        "✔ Rol competitivo (IGL / Fragger / Support)\n\n"
        "💰 *Planes:*\n"
        "• 5 USD → 30 días\n"
        "• 15 USD → para siempre (lifetime 🏆)\n\n"
        "1️⃣ Pagá el plan que quieras en PayPal:\n"
        "   • Mensual: https://paypal.me/botpremiumfort/5\n"
        "   • De por vida: https://paypal.me/botpremiumfort/15\n"
        "2️⃣ Volvé al bot, tocá *VER PREMIUM* en /menu y después *Ya pagué*.\n"
        "3️⃣ Enviá la *captura del pago* y el admin te activa.\n\n"
        "Si justo hoy hay un descuento activo, podés usar también `/codigo FNCS50`.",
        parse_mode="Markdown",
    )


async def validar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        codigo = context.args[0].upper()
    except Exception:
        await update.message.reply_text(
            "Uso correcto: `/codigo FNCS50`", parse_mode="Markdown"
        )
        return

    if not descuento_mensual_activo():
        await update.message.reply_text(
            "❌ No hay descuentos activos en este momento.\n"
            "El próximo descuento aparece automáticamente el *1° de cada mes*.",
            parse_mode="Markdown",
        )
        return

    if codigo != DESCUENTO_MENSUAL["codigo"]:
        await update.message.reply_text("❌ Código inválido.", parse_mode="Markdown")
        return

    porcentaje = int(DESCUENTO_MENSUAL["porcentaje"] * 100)
    precio_final = round(5 * (1 - DESCUENTO_MENSUAL["porcentaje"]), 2)

    await update.message.reply_text(
        f"🎟 *Código válido:* `{codigo}`\n"
        f"Descuento: {porcentaje}% sobre el plan mensual.\n"
        f"💰 Precio final: {precio_final} USD\n"
        f"⏳ Expira el: {DESCUENTO_MENSUAL['expira']}\n\n"
        f"Pagá aquí (mensual con descuento):\n"
        f"https://paypal.me/botpremiumfort/{precio_final}",
        parse_mode="Markdown",
    )


async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    xp_data = cargar_xp()
    xp = xp_data.get(str(uid), 0)
    lvl = get_level(xp)
    lvl_n = level_name(lvl)
    prem_info = obtener_info_premium(uid)

    refs = cargar_ref()
    info_ref = refs.get(str(uid), {"ref_by": None, "referred": [], "premios": []})
    ref_by = info_ref.get("ref_by")
    referred = info_ref.get("referred", [])
    premios = info_ref.get("premios", [])

    texto = (
        "📄 *Tu perfil competitivo*\n\n"
        f"🆔 ID: `{uid}`\n\n"
        f"⭐ Nivel: {lvl} – *{lvl_n}*\n"
        f"📈 XP total: {xp}\n\n"
        f"💎 Estado Premium: {prem_info}\n\n"
        f"👥 Referidos: {len(referred)}\n"
        f"🎁 Bonos obtenidos por referidos: {len(premios)}\n"
    )

    if ref_by:
        texto += f"\n🙋‍♂️ Te refirió el ID: `{ref_by}`"

    await update.message.reply_text(texto, parse_mode="Markdown")


async def referidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    refs = cargar_ref()
    info = refs.get(str(uid), {"ref_by": None, "referred": [], "premios": []})
    referred = info.get("referred", [])
    premios = info.get("premios", [])

    texto = (
        "🎟 *Sistema de referidos*\n\n"
        "Compartí tu ID con tus amigos. Cuando ellos lo usen y compren Premium, "
        "vos ganás *7 días de Premium* por cada uno.\n\n"
        f"🆔 *Tu código de referido:* `{uid}`\n\n"
        f"👥 Referidos registrados: {len(referred)}\n"
        f"🎁 Bonos ya usados: {len(premios)}\n\n"
        "Tus amigos tienen que usar:\n"
        f"`/usarref {uid}`\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def usarref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        ref_id = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "Uso correcto: `/usarref ID_AMIGO`", parse_mode="Markdown"
        )
        return

    msg = registrar_referido(user_id, ref_id)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def replay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎥 *Analizar replay / partida*\n\n"
        "Mandame un mensaje contando:\n"
        "• Dónde caíste\n"
        "• Qué loot tenías\n"
        "• En qué fase moriste (early / mid / late)\n"
        "• Cuántos mats tenías\n"
        "• Qué hizo el rival y qué intentaste hacer vos\n\n"
        "Y te explico qué podrías haber hecho distinto y cómo jugar esa situación como un jugador PRO.",
        parse_mode="Markdown",
    )
# ==========================
#   PANEL ADMIN
# ==========================


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    usuarios = cargar_usuarios()
    premium = cargar_premium()
    xp_data = cargar_xp()

    total_users = len(usuarios)
    total_premium = 0
    total_plus = 0
    total_life = 0

    for uid, entry in premium.items():
        if isinstance(entry, str):
            if not vencio_premium(entry):
                total_premium += 1
        else:
            plan = entry.get("plan", "standard")
            life = entry.get("lifetime", False)
            exp = entry.get("exp")

            if life:
                total_life += 1
                if plan == "plus":
                    total_plus += 1
                else:
                    total_premium += 1
            else:
                if exp and not vencio_premium(exp):
                    if plan == "plus":
                        total_plus += 1
                    else:
                        total_premium += 1

    texto = (
        "📊 *ESTADÍSTICAS DEL BOT*\n\n"
        f"👥 Usuarios totales: {total_users}\n"
        f"💎 Premium Standard activos: {total_premium}\n"
        f"💜 Premium PLUS activos: {total_plus}\n"
        f"🏆 Premium de por vida (incluye Plus): {total_life}\n"
        f"📈 Usuarios con XP registrado: {len(xp_data)}\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def premiumactivos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    premium = cargar_premium()
    lineas = []
    for uid, entry in premium.items():
        estado = "INACTIVO"
        plan = "Standard"
        life = False
        exp = None

        if isinstance(entry, str):
            life = False
            plan = "Standard"
            exp = entry
            if not vencio_premium(entry):
                estado = "ACTIVO"
        else:
            plan = entry.get("plan", "Standard")
            life = entry.get("lifetime", False)
            exp = entry.get("exp")
            if life:
                estado = "LIFE"
            else:
                if exp and not vencio_premium(exp):
                    estado = "ACTIVO"

        lineas.append(f"{uid} – {plan} – {estado} – exp: {exp}")

    if not lineas:
        texto = "No hay usuarios en el sistema premium."
    else:
        texto = "💎 *Premium registrados:*\n\n" + "\n".join(lineas[:120])

    await update.message.reply_text(texto, parse_mode="Markdown")


async def difundir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Uso: /difundir mensaje_para_todos", parse_mode="Markdown"
        )
        return

    msg = " ".join(context.args)
    usuarios = cargar_usuarios()
    enviados = 0
    for uid in usuarios:
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            enviados += 1
        except Exception:
            pass

    await update.message.reply_text(
        f"Mensaje enviado a {enviados} usuarios.", parse_mode="Markdown"
    )


async def competencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Modo competencia: top XP gana 7 días Premium."""
    if update.effective_user.id != ADMIN_ID:
        return

    xp_data = cargar_xp()
    if not xp_data:
        await update.message.reply_text(
            "No hay datos de XP todavía.", parse_mode="Markdown"
        )
        return

    # top 3 por XP
    top = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)[:3]

    texto = "🏆 *RESULTADOS COMPETENCIA XP*\n\n"
    pos = 1
    for uid_str, xp in top:
        uid = int(uid_str)
        add_days_premium(uid, 7, plan="standard")
        texto += f"{pos}️⃣ `{uid}` – {xp} XP → +7 días Premium\n"
        pos += 1
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    "🏆 *Felicitaciones!*\n\n"
                    "Fuiste top de XP en la competencia.\n"
                    "Ganaste *7 días de Premium extra*. 🔥"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await update.message.reply_text(texto, parse_mode="Markdown")


# ==========================
#  PREMIUM / BOTONES
# ==========================


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    user = q.from_user.id

    registrar_usuario(user)

    # Usuario abre sección de compra
    if data == "buy_premium":
        await q.message.reply_text(
            "━━━━━━━━━━━━━━━━━━\n"
            "💎 *MODO PREMIUM – COACH FORTNITE PRO*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✔ Chat IA PRO ilimitado\n"
            "✔ Rutinas diarias personalizadas\n"
            "✔ Drops competitivos y rotaciones PRO\n"
            "✔ Optimización de PC para más FPS\n"
            "✔ Análisis de partidas y de tu nivel\n"
            "✔ Roles, mentalidad y plan de mejora\n\n"
            "💰 *Planes disponibles:*\n"
            "• 5 USD → 30 días (plan mensual Standard)\n"
            "• 15 USD → para siempre (lifetime 🏆)\n\n"
            "1️⃣ Pagá el plan que quieras en PayPal:\n"
            "   • Mensual: https://paypal.me/botpremiumfort/5\n"
            "   • De por vida: https://paypal.me/botpremiumfort/15\n"
            "2️⃣ Volvé al bot y tocá *Ya pagué*.\n"
            "3️⃣ Enviá la *captura del pago* y el admin te activa.\n",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✔ Ya pagué", callback_data="ya_pague")]]
            ),
            parse_mode="Markdown",
        )
        return

    # Usuario dice "ya pagué"
    if data == "ya_pague":
        await q.message.reply_text(
            "📸 *Perfecto.*\n"
            "Ahora enviame acá mismo la *captura del pago en PayPal*.\n"
            "El admin la va a revisar y, si todo está ok, te activa el Premium "
            "(mensual o de por vida, según lo que hayas pagado). 💎",
            parse_mode="Markdown",
        )
        return

    # Secciones gratuitas
    if data in ["cfg", "sens", "combos", "duo", "mento"]:
        await q.message.reply_text(text_section(data), parse_mode="Markdown")
        return

    # Secciones SOLO PREMIUM (sumamos XP cuando las usan)
    if data in ["entreno", "mapas", "optimizar", "rol", "analizar", "resumen"]:
        if not es_premium(user):
            await q.message.reply_text(
                "🔒 *Esta sección es exclusiva de usuarios PREMIUM.*\n\n"
                "Desbloqueás rutinas diarias, drops competitivos, optimización de PC y "
                "análisis de partidas y nivel.\n\n"
                "Usá /premiuminfo o /menu y tocá *VER PREMIUM* para ver los planes.",
                parse_mode="Markdown",
            )
            return

        await q.message.reply_text(text_section(data), parse_mode="Markdown")

        # XP por usar herramientas PRO
        if data in ["entreno", "mapas", "analizar", "resumen"]:
            add_xp(user, 10)
        else:
            add_xp(user, 5)

        return


# ==========================
#   FOTO → REENVÍO AL ADMIN
# ==========================


async def handle_payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    registrar_usuario(user_id)

    try:
        file_id = update.message.photo[-1].file_id

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=f"📸 *Captura de pago recibida del usuario:* `{user_id}`",
            parse_mode="Markdown",
        )

        await update.message.reply_text(
            "📤 *Recibí tu captura.*\n"
            "El admin la va a revisar y, si todo está bien, te activa el Premium. 💎",
            parse_mode="Markdown",
        )

    except Exception:
        await update.message.reply_text(
            "⚠️ Hubo un error al recibir la captura. Probá de nuevo.",
            parse_mode="Markdown",
        )
# ==========================
#   CHAT IA PREMIUM + GANCHOS
# ==========================

GREETINGS = ["hola", "holaa", "buenas", "buenass", "hello", "ola", "hi", "buenas tardes", "buenos dias", "buenas noches"]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    registrar_usuario(uid)

    text = update.message.text or ""
    low = text.lower().strip()

    # 1) Saludos o pedido de ayuda → mostrar /start
    if any(low.startswith(g) for g in GREETINGS) or "ayuda" in low or "coach" in low:
        await start(update, context)
        return

    # 2) Sens de PROS exacta (Clix, Peterbot, Pollo, Bugha, etc.)
    resp_sens = obtener_sens_pro_desde_texto(low)
    if resp_sens:
        await update.message.reply_text(resp_sens, parse_mode="Markdown")
        return

    # 3) Frases relacionadas con premium / pagar
    if "premium" in low or "pagar" in low or "pago" in low or "precio" in low:
        await update.message.reply_text(
            "💎 *Premium incluye:*\n"
            "• Chat IA PRO ilimitado\n"
            "• Rutinas diarias\n"
            "• Drops competitivos\n"
            "• Optimización de PC\n"
            "• Análisis de partidas y nivel\n\n"
            "Usá /premiuminfo o /menu y tocá *VER PREMIUM* para ver cómo activarlo.",
            parse_mode="Markdown",
        )
        return

    # 4) Mensajes sobre sensibilidades de pros en general
    if (
        "sens pros" in low
        or "sensibilidad de pros" in low
        or "sensibilidades de pros" in low
    ):
        await update.message.reply_text(
            "🧩 *Sensibilidades de PROS*\n\n"
            "Puedo darte sens exactas de varios pros (Clix, Bugha, Peterbot, Pollo, etc.) "
            "y también armarte una sens personalizada basada en ellos.\n\n"
            "Mandame tu DPI, resolución y estilo (agresivo/pasivo) y te ajusto algo a tu medida.",
            parse_mode="Markdown",
        )
        return

    # 5) Si NO es Premium, no puede usar IA PRO libre
    if not es_premium(uid):
        await update.message.reply_text(
            "🤖 El chat IA avanzado es solo para *usuarios PREMIUM*.\n\n"
            "Usá /premiuminfo o /menu y tocá *VER PREMIUM* para ver cómo activarlo.",
            parse_mode="Markdown",
        )
        return

    # 6) IA PRO (solo para Premium) + XP
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sos un COACH PROFESIONAL de Fortnite competitivo (FNCS, Cash Cups, scrims). "
                        "Respondés SIEMPRE en español, directo, concreto y útil. "
                        "Dás consejos de configuración, sens, AIM, mecánicas, rotaciones, mentalidad, "
                        "y todo lo relacionado al rendimiento competitivo en Fortnite."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        reply = r.choices[0].message.content
        await update.message.reply_text(reply)
        add_xp(uid, 5)

    except Exception:
        await update.message.reply_text("⚠️ Hubo un problema al hablar con la IA.")


# ==========================
#   DESCUENTO MENSUAL AUTOMÁTICO
# ==========================


async def activar_descuento_mensual(context: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now()

    # Solo se activa el día 1 del mes
    if hoy.day != 1:
        return

    # Activar descuento por 24 horas
    DESCUENTO_MENSUAL["activo"] = True
    DESCUENTO_MENSUAL["expira"] = (hoy + timedelta(hours=24)).strftime(
        "%Y-%m-%d %H:%M"
    )

    mensaje = (
        "🎉 *DESCUENTO MENSUAL ACTIVADO*\n\n"
        "Por las próximas *24 horas*, podés usar el código:\n\n"
        "🎟 Código: *FNCS50*\n"
        "💰 Descuento: 50%\n"
        "📦 Aplica solo al plan mensual (5 USD → 2.50 USD)\n\n"
        "🔥 Aprovechalo antes de que expire.\n\n"
        "Usá el comando:\n"
        "👉 /codigo FNCS50\n\n"
        "O pagá directamente aquí (ya con el descuento aplicado):\n"
        "➡ https://paypal.me/botpremiumfort/2.5"
    )

    usuarios = cargar_usuarios()
    for uid in usuarios:
        try:
            await context.bot.send_message(
                chat_id=uid, text=mensaje, parse_mode="Markdown"
            )
        except Exception:
            pass

    # Aviso al admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text="📣 El descuento mensual fue activado y enviado a todos los usuarios.",
        parse_mode="Markdown",
    )


# ==========================
#   WARM-UP DIARIO PRO
# ==========================

WARMUPS = [
    "🔥 *Warm-up del día (30 min)*\n\n"
    "• 10 min AIM (Raider464 / Skavook)\n"
    "• 10 min Edits rápidos\n"
    "• 10 min Realistics 1v1\n\n"
    "Focus de hoy: *no sobre-editar, solo piezas necesarias.*",

    "🔥 *Warm-up del día (25 min)*\n\n"
    "• 5 min tracking con AR\n"
    "• 10 min piece control\n"
    "• 10 min Zone Wars\n\n"
    "Focus de hoy: *rotar antes, no tarde.*",

    "🔥 *Warm-up del día (20 min)*\n\n"
    "• 5 min flicks con escopeta\n"
    "• 5 min edits simples\n"
    "• 10 min box fights\n\n"
    "Focus de hoy: *no pushear sin ángulo.*",
]


async def enviar_warmup_diario(context: ContextTypes.DEFAULT_TYPE):
    import random

    warmup = random.choice(WARMUPS)
    premium = cargar_premium()

    for uid_str, entry in premium.items():
        uid = int(uid_str)
        if not es_premium(uid):
            continue
        try:
            await context.bot.send_message(
                chat_id=uid, text=warmup, parse_mode="Markdown"
            )
        except Exception:
            pass


# ==========================
#   ADMIN: ACTIVAR PREMIUM
# ==========================


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /premium <id> <dias|life>
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Este comando es solo para el admin.")
        return

    try:
        uid_str = str(context.args[0])
        modo = context.args[1].lower()
        uid_int = int(uid_str)

        data = cargar_premium()

        if modo in ["life", "lifetime", "vida", "perma", "permanente"]:
            data[uid_str] = {
                "lifetime": True,
                "exp": None,
                "plan": "standard",
            }
            guardar_premium(data)

            await update.message.reply_text(
                f"✅ *Premium DE POR VIDA activado para {uid_str}* 🏆",
                parse_mode="Markdown",
            )

            try:
                await context.bot.send_message(
                    chat_id=uid_int,
                    text=(
                        "🏆 *Tu Premium de por vida fue activado.*\n\n"
                        "Tenés acceso completo para SIEMPRE:\n"
                        "• IA PRO ilimitada\n"
                        "• Rutinas diarias\n"
                        "• Drops competitivos\n"
                        "• Optimización de PC\n"
                        "• Análisis de partidas y nivel\n\n"
                        "Empezá mandándome qué querés mejorar primero. 🔥"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        else:
            dias = int(modo)
            add_days_premium(uid_int, dias, plan="standard")

            data = cargar_premium()
            entry = data[uid_str]
            exp_str = entry["exp"] if isinstance(entry, dict) else entry

            await update.message.reply_text(
                f"✅ *Premium activado para {uid_str} por {dias} días*\n"
                f"📅 Expira: {exp_str}",
                parse_mode="Markdown",
            )

            try:
                await context.bot.send_message(
                    chat_id=uid_int,
                    text=(
                        f"💎 *Tu Premium fue activado por {dias} días.*\n"
                        f"📅 Expira el: {exp_str}\n\n"
                        "Ya podés usar el chat IA PRO, rutinas, drops competitivos y más.\n"
                        "Decime qué querés mejorar primero. 🔥"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # Procesar bonus referido si corresponde
        procesar_bonus_referido(uid_str)

    except Exception:
        await update.message.reply_text(
            "Uso correcto:\n"
            "/premium <id> <dias|life>\n\n"
            "Ejemplos:\n"
            "/premium 123456789 30   → 30 días\n"
            "/premium 123456789 life → de por vida",
            parse_mode="Markdown",
        )


async def premiumplus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /premiumplus <id> <dias|life>
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Este comando es solo para el admin.")
        return

    try:
        uid_str = str(context.args[0])
        modo = context.args[1].lower()
        uid_int = int(uid_str)

        data = cargar_premium()

        if modo in ["life", "lifetime", "vida", "perma", "permanente"]:
            data[uid_str] = {
                "lifetime": True,
                "exp": None,
                "plan": "plus",
            }
            guardar_premium(data)

            await update.message.reply_text(
                f"✅ *Premium PLUS DE POR VIDA activado para {uid_str}* 🏆",
                parse_mode="Markdown",
            )

            try:
                await context.bot.send_message(
                    chat_id=uid_int,
                    text=(
                        "💜 *Tu Premium PLUS de por vida fue activado.*\n\n"
                        "Incluye todo el Premium normal + priorización en warm-ups, "
                        "análisis y soporte.\n\n"
                        "Empezá mandándome qué querés mejorar primero. 🔥"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        else:
            dias = int(modo)
            add_days_premium(uid_int, dias, plan="plus")

            data = cargar_premium()
            entry = data[uid_str]
            exp_str = entry["exp"] if isinstance(entry, dict) else entry

            await update.message.reply_text(
                f"✅ *Premium PLUS activado para {uid_str} por {dias} días*\n"
                f"📅 Expira: {exp_str}",
                parse_mode="Markdown",
            )

            try:
                await context.bot.send_message(
                    chat_id=uid_int,
                    text=(
                        f"💜 *Tu Premium PLUS fue activado por {dias} días.*\n"
                        f"📅 Expira el: {exp_str}\n\n"
                        "Tenés todo el contenido PRO + prioridad.\n"
                        "Decime qué querés mejorar primero. 🔥"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # Bonus referido también aplica
        procesar_bonus_referido(uid_str)

    except Exception:
        await update.message.reply_text(
            "Uso correcto:\n"
            "/premiumplus <id> <dias|life>\n\n"
            "Ejemplos:\n"
            "/premiumplus 123456789 30   → 30 días\n"
            "/premiumplus 123456789 life → de por vida",
            parse_mode="Markdown",
        )


# ==========================
#   MAIN
# ==========================


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Comandos normales
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("premiuminfo", premiuminfo))
    app.add_handler(CommandHandler("codigo", validar_codigo))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("referidos", referidos))
    app.add_handler(CommandHandler("usarref", usarref))
    app.add_handler(CommandHandler("replay", replay_cmd))

    # Panel admin
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("premiumactivos", premiumactivos))
    app.add_handler(CommandHandler("difundir", difundir))
    app.add_handler(CommandHandler("competencia", competencia))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("premiumplus", premiumplus_command))

    # Botones
    app.add_handler(CallbackQueryHandler(button_handler))

    # Fotos (capturas de pago)
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_photo))

    # Chat IA / texto general
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

   # Jobs programados (desactivados de momento)
   # job = app.job_queue
   # job.run_daily(activar_descuento_mensual, time=dtime(hour=0, minute=0))
   # job.run_daily(enviar_warmup_diario, time=dtime(hour=15, minute=0))


    print("🤖 BOT FORTNITE PREMIUM RUNNING...")
    app.run_polling()


if __name__ == "__main__":

    main()

