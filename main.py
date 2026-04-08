import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder


@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
    admin_id: int = int(os.getenv("ADMIN_ID", "172433210"))


config = Config()
CONTENT_PATH = Path(__file__).parent / "data" / "content.json"


class ReportIssueState(StatesGroup):
    waiting_description = State()


class AdminState(StatesGroup):
    waiting_editor_add_id = State()
    waiting_district_add_name = State()
    waiting_district_rename_name = State()

    waiting_apartment_add_address = State()
    waiting_apartment_add_coords = State()
    waiting_apartment_add_wifi_login = State()
    waiting_apartment_add_wifi_pass = State()
    waiting_apartment_add_checkin = State()
    waiting_apartment_add_appliances = State()
    waiting_apartment_edit_value = State()

    waiting_faq_add_question = State()
    waiting_faq_add_answer = State()
    waiting_faq_edit_question = State()
    waiting_faq_edit_answer = State()

    waiting_rules_text = State()


def load_content(file_path: Path) -> dict[str, Any]:
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required_keys = {"districts", "apartments", "faq", "rules"}
    missing = required_keys - set(data.keys())
    if missing:
        raise ValueError(f"content.json missing keys: {', '.join(sorted(missing))}")

    if "editors" not in data:
        data["editors"] = []

    if not isinstance(data["apartments"], list):
        raise ValueError("content.json apartments must be a list")

    return data


content = load_content(CONTENT_PATH)


def save_content() -> None:
    with CONTENT_PATH.open("w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)


def get_districts() -> list[str]:
    return content["districts"]


def get_apartments() -> list[dict[str, Any]]:
    return content["apartments"]


def get_faq_items() -> list[dict[str, str]]:
    return content["faq"]


def get_rules_text() -> str:
    return content["rules"]


def get_editors() -> list[int]:
    editors = content.get("editors", [])
    normalized: list[int] = []
    for value in editors:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    content["editors"] = normalized
    return normalized


def is_editor(user_id: int) -> bool:
    return user_id == config.admin_id or user_id in get_editors()


def is_super_admin(user_id: int) -> bool:
    return user_id == config.admin_id


def get_apartment(apartment_id: int) -> dict[str, Any] | None:
    return next((a for a in get_apartments() if a["id"] == apartment_id), None)


def get_apartments_by_district(district_name: str) -> list[dict[str, Any]]:
    return [a for a in get_apartments() if a["district"] == district_name]


def get_next_apartment_id() -> int:
    apartments = get_apartments()
    if not apartments:
        return 1
    return max(int(a["id"]) for a in apartments) + 1


def escape_multiline(text: str) -> str:
    return html.escape(text)


def main_menu_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📍 Выбрать адрес", callback_data="menu:districts"))
    kb.row(InlineKeyboardButton(text="📜 Правила и штрафы", callback_data="menu:rules"))
    kb.row(InlineKeyboardButton(text="❓ FAQ", callback_data="menu:faq"))
    kb.row(InlineKeyboardButton(text="🆘 Помощь", callback_data="menu:help"))
    if is_editor(user_id):
        kb.row(InlineKeyboardButton(text="⚙️ Админ панель", callback_data="adm:main"))
    return kb.as_markup()


def districts_kb(back_cb: str = "menu:main"):
    kb = InlineKeyboardBuilder()
    for idx, district in enumerate(get_districts()):
        kb.row(InlineKeyboardButton(text=district, callback_data=f"district:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb))
    return kb.as_markup()


def addresses_kb(district_idx: int):
    districts = get_districts()
    district_name = districts[district_idx]
    apartments = get_apartments_by_district(district_name)

    kb = InlineKeyboardBuilder()
    for apt in apartments:
        kb.row(InlineKeyboardButton(text=apt["address"], callback_data=f"apartment:{apt['id']}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:districts"))
    return kb.as_markup()


def apartment_card_kb(apartment: dict[str, Any]):
    districts = get_districts()
    district_idx = districts.index(apartment["district"]) if apartment["district"] in districts else 0
    apt_id = apartment["id"]

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Инструкция по заселению", callback_data=f"apt_action:checkin:{apt_id}"))
    kb.row(InlineKeyboardButton(text="Wi-Fi", callback_data=f"apt_action:wifi:{apt_id}"))
    kb.row(InlineKeyboardButton(text="Бытовая техника", callback_data=f"apt_action:appliances:{apt_id}"))
    kb.row(InlineKeyboardButton(text="Карта", callback_data=f"apt_action:map:{apt_id}"))
    kb.row(InlineKeyboardButton(text="Сообщить о проблеме", callback_data=f"apt_action:report:{apt_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"district:{district_idx}"))
    return kb.as_markup()


def faq_list_kb():
    kb = InlineKeyboardBuilder()
    for idx, item in enumerate(get_faq_items()):
        kb.row(InlineKeyboardButton(text=item["question"], callback_data=f"faq:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    return kb.as_markup()


def back_to_apartment_kb(apartment_id: int):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"apartment:{apartment_id}"))
    return kb.as_markup()


def admin_main_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🏙 Районы", callback_data="adm:dist"))
    kb.row(InlineKeyboardButton(text="🏠 Квартиры", callback_data="adm:apt"))
    kb.row(InlineKeyboardButton(text="❓ FAQ", callback_data="adm:faq"))
    kb.row(InlineKeyboardButton(text="📜 Правила", callback_data="adm:rules"))
    if is_super_admin(user_id):
        kb.row(InlineKeyboardButton(text="👥 Редакторы", callback_data="adm:ed"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    return kb.as_markup()


def editors_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Добавить редактора", callback_data="adm:ed:add"))
    editors = get_editors()
    if editors:
        for editor_id in editors:
            kb.row(InlineKeyboardButton(text=f"➖ Удалить {editor_id}", callback_data=f"adm:ed:rm:{editor_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main"))
    return kb.as_markup()


def districts_admin_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Добавить район", callback_data="adm:dist:add"))
    for idx, district in enumerate(get_districts()):
        kb.row(InlineKeyboardButton(text=f"✏️ {district}", callback_data=f"adm:dist:ren:{idx}"))
        kb.row(InlineKeyboardButton(text=f"🗑 Удалить {district}", callback_data=f"adm:dist:del:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main"))
    return kb.as_markup()


def apartments_admin_districts_kb():
    kb = InlineKeyboardBuilder()
    for idx, district in enumerate(get_districts()):
        kb.row(InlineKeyboardButton(text=district, callback_data=f"adm:apt:d:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main"))
    return kb.as_markup()


def apartments_admin_list_kb(district_idx: int):
    district_name = get_districts()[district_idx]
    apartments = get_apartments_by_district(district_name)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Добавить квартиру", callback_data=f"adm:apt:add:{district_idx}"))
    for apt in apartments:
        kb.row(InlineKeyboardButton(text=f"✏️ {apt['address']}", callback_data=f"adm:apt:s:{apt['id']}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:apt"))
    return kb.as_markup()


def apartment_admin_card_kb(apartment_id: int):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ Адрес", callback_data=f"adm:apt:f:ad:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Ссылка на карту", callback_data=f"adm:apt:f:co:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Wi-Fi логин", callback_data=f"adm:apt:f:wl:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Wi-Fi пароль", callback_data=f"adm:apt:f:wp:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Инструкция заселения", callback_data=f"adm:apt:f:ci:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Бытовая техника", callback_data=f"adm:apt:f:ag:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="🔁 Переместить район", callback_data=f"adm:apt:mvsel:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="🗑 Удалить квартиру", callback_data=f"adm:apt:del:{apartment_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:apt"))
    return kb.as_markup()


def apartment_move_district_kb(apartment_id: int):
    kb = InlineKeyboardBuilder()
    for idx, district in enumerate(get_districts()):
        kb.row(InlineKeyboardButton(text=district, callback_data=f"adm:apt:mv:{apartment_id}:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm:apt:s:{apartment_id}"))
    return kb.as_markup()


def faq_admin_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="adm:faq:add"))
    for idx, item in enumerate(get_faq_items()):
        title = item["question"]
        if len(title) > 60:
            title = title[:57] + "..."
        kb.row(InlineKeyboardButton(text=f"✏️ {title}", callback_data=f"adm:faq:s:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main"))
    return kb.as_markup()


def faq_item_admin_kb(idx: int):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ Вопрос", callback_data=f"adm:faq:eq:{idx}"))
    kb.row(InlineKeyboardButton(text="✏️ Ответ", callback_data=f"adm:faq:ea:{idx}"))
    kb.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:faq:del:{idx}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:faq"))
    return kb.as_markup()


def rules_admin_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ Изменить текст правил", callback_data="adm:rules:edit"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main"))
    return kb.as_markup()


def prompt_back_kb(callback_back: str):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_back))
    return kb.as_markup()


async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None):
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text=text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


async def require_editor(callback: CallbackQuery, state: FSMContext) -> bool:
    user = callback.from_user
    if user is None or not is_editor(user.id):
        await state.clear()
        await callback.answer("Нет доступа", show_alert=True)
        return False
    return True


router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    text = (
        "<b>Добро пожаловать в бот-справочник посуточной аренды в Красноярске</b>\n\n"
        "Выберите нужный раздел:"
    )
    await message.answer(text, reply_markup=main_menu_kb(user_id))


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    if not is_editor(user_id):
        await message.answer("⛔️ У вас нет доступа к админ панели.")
        return
    await state.clear()
    await message.answer("<b>Админ панель</b>\nВыберите раздел:", reply_markup=admin_main_kb(user_id))


@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    text = "<b>Главное меню</b>\nВыберите нужный раздел:"
    await safe_edit_text(callback, text, main_menu_kb(user_id))
    await callback.answer()


@router.callback_query(F.data == "menu:districts")
async def menu_districts(callback: CallbackQuery):
    text = "<b>Выбор района</b>\nВыберите район:"
    await safe_edit_text(callback, text, districts_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:rules")
async def menu_rules(callback: CallbackQuery):
    text = f"<b>Правила проживания и штрафы</b>\n\n{escape_multiline(get_rules_text())}"
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    await safe_edit_text(callback, text, kb.as_markup())
    await callback.answer()


@router.callback_query(F.data == "menu:faq")
async def menu_faq(callback: CallbackQuery):
    text = "<b>FAQ</b>\nВыберите вопрос:"
    await safe_edit_text(callback, text, faq_list_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def menu_help(callback: CallbackQuery):
    text = (
        "<b>Помощь</b>\n\n"
        "Если не нашли нужную информацию:\n"
        "1) Откройте карточку вашей квартиры\n"
        "2) Нажмите <b>Сообщить о проблеме</b>\n"
        "3) Отправьте описание проблемы\n\n"
        "Администратор ответит как можно быстрее."
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    await safe_edit_text(callback, text, kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("district:"))
async def district_selected(callback: CallbackQuery):
    district_idx = int(callback.data.split(":")[1])
    districts = get_districts()
    if district_idx < 0 or district_idx >= len(districts):
        await callback.answer("Район не найден", show_alert=True)
        return
    district_name = districts[district_idx]
    text = f"<b>{escape_multiline(district_name)}</b>\nВыберите адрес:"
    await safe_edit_text(callback, text, addresses_kb(district_idx))
    await callback.answer()


@router.callback_query(F.data.startswith("apartment:"))
async def apartment_selected(callback: CallbackQuery):
    apartment_id = int(callback.data.split(":")[1])
    apt = get_apartment(apartment_id)
    if apt is None:
        await callback.answer("Квартира не найдена", show_alert=True)
        return

    text = (
        "<b>Карточка квартиры</b>\n\n"
        f"<b>Адрес:</b> {escape_multiline(apt['address'])}\n"
        f"<b>Район:</b> {escape_multiline(apt['district'])}\n\n"
        "Выберите нужный раздел:"
    )
    await safe_edit_text(callback, text, apartment_card_kb(apt))
    await callback.answer()


@router.callback_query(F.data.startswith("apt_action:"))
async def apartment_actions(callback: CallbackQuery, state: FSMContext):
    _, action, apt_id_str = callback.data.split(":")
    apartment_id = int(apt_id_str)
    apt = get_apartment(apartment_id)

    if apt is None:
        await callback.answer("Квартира не найдена", show_alert=True)
        return

    if action == "checkin":
        text = (
            "<b>Инструкция по заселению</b>\n\n"
            f"<b>Адрес:</b> {escape_multiline(apt['address'])}\n"
            f"{escape_multiline(apt['check_in_instruction'])}"
        )
        await safe_edit_text(callback, text, back_to_apartment_kb(apartment_id))

    elif action == "wifi":
        text = (
            "<b>Wi-Fi</b>\n\n"
            f"<b>Сеть:</b> {escape_multiline(apt['wifi_login'])}\n"
            f"<b>Пароль:</b> <code>{escape_multiline(apt['wifi_pass'])}</code>\n\n"
            f"<b>Адрес:</b> {escape_multiline(apt['address'])}"
        )
        await safe_edit_text(callback, text, back_to_apartment_kb(apartment_id))

    elif action == "appliances":
        text = (
            "<b>Бытовая техника</b>\n\n"
            f"<b>Адрес:</b> {escape_multiline(apt['address'])}\n"
            f"{escape_multiline(apt['appliances_guide'])}"
        )
        await safe_edit_text(callback, text, back_to_apartment_kb(apartment_id))

    elif action == "map":
        text = (
            "<b>Карта</b>\n\n"
            f"<b>Адрес:</b> {escape_multiline(apt['address'])}\n"
            f"<a href=\"{escape_multiline(apt['coords_link'])}\">Открыть на карте</a>"
        )
        await safe_edit_text(callback, text, back_to_apartment_kb(apartment_id))

    elif action == "report":
        await state.set_state(ReportIssueState.waiting_description)
        await state.update_data(apartment_id=apartment_id)
        text = (
            "<b>Сообщить о проблеме</b>\n\n"
            f"<b>Квартира:</b> {escape_multiline(apt['address'])}\n"
            "Отправьте одним сообщением описание проблемы."
        )
        await safe_edit_text(callback, text, prompt_back_kb(f"apartment:{apartment_id}"))

    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    await callback.answer()


@router.callback_query(F.data.startswith("faq:"))
async def faq_answer(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    faq_items = get_faq_items()
    if idx < 0 or idx >= len(faq_items):
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    item = faq_items[idx]
    text = f"<b>{escape_multiline(item['question'])}</b>\n\n{escape_multiline(item['answer'])}"
    await safe_edit_text(callback, text, prompt_back_kb("menu:faq"))
    await callback.answer()


@router.message(ReportIssueState.waiting_description)
async def issue_description_received(message: Message, state: FSMContext, bot: Bot):
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, отправьте текстовое описание проблемы.")
        return

    data = await state.get_data()
    apartment_id = data.get("apartment_id")
    apt = get_apartment(apartment_id) if apartment_id is not None else None

    address = apt["address"] if apt else "Неизвестный адрес"
    user = message.from_user
    username = f"@{user.username}" if user and user.username else "без username"
    full_name = user.full_name if user else "Unknown"
    user_id = user.id if user else 0

    admin_text = (
        "<b>Новое сообщение о проблеме</b>\n\n"
        f"<b>Квартира:</b> {escape_multiline(address)}\n"
        f"<b>Гость:</b> {escape_multiline(full_name)} ({escape_multiline(username)})\n"
        f"<b>User ID:</b> {user_id}\n\n"
        f"<b>Описание:</b>\n{escape_multiline(message.text)}"
    )

    await bot.send_message(chat_id=config.admin_id, text=admin_text)

    kb = InlineKeyboardBuilder()
    if apartment_id is not None:
        kb.row(InlineKeyboardButton(text="⬅️ В карточку квартиры", callback_data=f"apartment:{apartment_id}"))
    else:
        kb.row(InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu:main"))

    await message.answer("✅ Спасибо! Сообщение отправлено администратору.", reply_markup=kb.as_markup())
    await state.clear()


# ----------------- Админ панель -----------------

@router.callback_query(F.data == "adm:main")
async def admin_main(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    await safe_edit_text(callback, "<b>Админ панель</b>\nВыберите раздел:", admin_main_kb(user_id))
    await callback.answer()


@router.callback_query(F.data == "adm:ed")
async def admin_editors(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Раздел доступен только главному админу", show_alert=True)
        return
    await state.clear()
    text = "<b>Редакторы</b>\n\nДобавляйте пользователей по их Telegram ID."
    await safe_edit_text(callback, text, editors_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:ed:add")
async def admin_editor_add_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminState.waiting_editor_add_id)
    text = "<b>Добавление редактора</b>\n\nОтправьте Telegram ID пользователя одним сообщением."
    await safe_edit_text(callback, text, prompt_back_kb("adm:ed"))
    await callback.answer()


@router.message(AdminState.waiting_editor_add_id)
async def admin_editor_add_finish(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    if not is_super_admin(user_id):
        await state.clear()
        await message.answer("⛔️ Нет доступа.")
        return

    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно отправить только число (Telegram ID).")
        return

    new_editor = int(raw)
    if new_editor == config.admin_id:
        await message.answer("Этот ID уже главный админ.")
        return

    editors = get_editors()
    if new_editor in editors:
        await message.answer("Этот пользователь уже редактор.")
        return

    editors.append(new_editor)
    content["editors"] = editors
    save_content()
    await state.clear()
    await message.answer(f"✅ Редактор {new_editor} добавлен.\nОткройте /admin для продолжения.")


@router.callback_query(F.data.startswith("adm:ed:rm:"))
async def admin_editor_remove(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    editor_id = int(callback.data.split(":")[3])
    editors = get_editors()
    if editor_id in editors:
        editors.remove(editor_id)
        content["editors"] = editors
        save_content()

    await safe_edit_text(callback, "<b>Редакторы</b>", editors_kb())
    await callback.answer("Удалено")


@router.callback_query(F.data == "adm:dist")
async def admin_districts(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.clear()
    text = "<b>Управление районами</b>\nВыберите действие:"
    await safe_edit_text(callback, text, districts_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:dist:add")
async def admin_district_add_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.set_state(AdminState.waiting_district_add_name)
    await safe_edit_text(
        callback,
        "<b>Добавление района</b>\n\nОтправьте название района одним сообщением.",
        prompt_back_kb("adm:dist"),
    )
    await callback.answer()


@router.message(AdminState.waiting_district_add_name)
async def admin_district_add_finish(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    if not is_editor(user_id):
        await state.clear()
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.")
        return
    districts = get_districts()
    if name in districts:
        await message.answer("Такой район уже есть.")
        return
    districts.append(name)
    save_content()
    await state.clear()
    await message.answer(f"✅ Район «{name}» добавлен.\nОткройте /admin для продолжения.")


@router.callback_query(F.data.startswith("adm:dist:ren:"))
async def admin_district_rename_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    idx = int(callback.data.split(":")[3])
    districts = get_districts()
    if idx < 0 or idx >= len(districts):
        await callback.answer("Район не найден", show_alert=True)
        return

    await state.set_state(AdminState.waiting_district_rename_name)
    await state.update_data(rename_district_idx=idx)
    old_name = districts[idx]
    text = (
        "<b>Переименование района</b>\n\n"
        f"Старое название: {escape_multiline(old_name)}\n"
        "Отправьте новое название одним сообщением."
    )
    await safe_edit_text(callback, text, prompt_back_kb("adm:dist"))
    await callback.answer()


@router.message(AdminState.waiting_district_rename_name)
async def admin_district_rename_finish(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    if not is_editor(user_id):
        await state.clear()
        return
    data = await state.get_data()
    idx = data.get("rename_district_idx")
    districts = get_districts()
    if idx is None or idx < 0 or idx >= len(districts):
        await state.clear()
        await message.answer("Ошибка: район не найден.")
        return
    new_name = (message.text or "").strip()
    if not new_name:
        await message.answer("Название не может быть пустым.")
        return
    old_name = districts[idx]
    districts[idx] = new_name
    for apt in get_apartments():
        if apt["district"] == old_name:
            apt["district"] = new_name
    save_content()
    await state.clear()
    await message.answer(f"✅ Район переименован: {old_name} -> {new_name}.\nОткройте /admin.")


@router.callback_query(F.data.startswith("adm:dist:del:"))
async def admin_district_delete(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    idx = int(callback.data.split(":")[3])
    districts = get_districts()
    if idx < 0 or idx >= len(districts):
        await callback.answer("Район не найден", show_alert=True)
        return
    district_name = districts[idx]

    used = any(a["district"] == district_name for a in get_apartments())
    if used:
        await callback.answer("Сначала удалите или перенесите квартиры из района", show_alert=True)
        return

    districts.pop(idx)
    save_content()
    await safe_edit_text(callback, "<b>Управление районами</b>", districts_admin_kb())
    await callback.answer("Район удален")


@router.callback_query(F.data == "adm:apt")
async def admin_apartments(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.clear()
    text = "<b>Квартиры</b>\nВыберите район:"
    await safe_edit_text(callback, text, apartments_admin_districts_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:apt:d:"))
async def admin_apartments_in_district(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    district_idx = int(callback.data.split(":")[3])
    districts = get_districts()
    if district_idx < 0 or district_idx >= len(districts):
        await callback.answer("Район не найден", show_alert=True)
        return
    district_name = districts[district_idx]
    text = f"<b>{escape_multiline(district_name)}</b>\nВыберите квартиру или добавьте новую:"
    await safe_edit_text(callback, text, apartments_admin_list_kb(district_idx))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:apt:add:"))
async def admin_apartment_add_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    district_idx = int(callback.data.split(":")[3])
    districts = get_districts()
    if district_idx < 0 or district_idx >= len(districts):
        await callback.answer("Район не найден", show_alert=True)
        return

    await state.set_state(AdminState.waiting_apartment_add_address)
    await state.update_data(new_apartment={"district": districts[district_idx]}, back_district_idx=district_idx)
    text = "<b>Новая квартира</b>\n\nШаг 1/6: отправьте адрес (например: ул. Молокова, 1)."
    await safe_edit_text(callback, text, prompt_back_kb(f"adm:apt:d:{district_idx}"))
    await callback.answer()


@router.message(AdminState.waiting_apartment_add_address)
async def admin_apartment_add_address(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Адрес не может быть пустым.")
        return
    data = await state.get_data()
    apt = data.get("new_apartment", {})
    apt["address"] = value
    await state.update_data(new_apartment=apt)
    await state.set_state(AdminState.waiting_apartment_add_coords)
    await message.answer("Шаг 2/6: отправьте ссылку на карту (Yandex/Google).")


@router.message(AdminState.waiting_apartment_add_coords)
async def admin_apartment_add_coords(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value.startswith("http"):
        await message.answer("Нужна ссылка, начинающаяся с http или https.")
        return
    data = await state.get_data()
    apt = data.get("new_apartment", {})
    apt["coords_link"] = value
    await state.update_data(new_apartment=apt)
    await state.set_state(AdminState.waiting_apartment_add_wifi_login)
    await message.answer("Шаг 3/6: отправьте Wi-Fi логин (имя сети).")


@router.message(AdminState.waiting_apartment_add_wifi_login)
async def admin_apartment_add_wifi_login(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Логин Wi-Fi не может быть пустым.")
        return
    data = await state.get_data()
    apt = data.get("new_apartment", {})
    apt["wifi_login"] = value
    await state.update_data(new_apartment=apt)
    await state.set_state(AdminState.waiting_apartment_add_wifi_pass)
    await message.answer("Шаг 4/6: отправьте Wi-Fi пароль.")


@router.message(AdminState.waiting_apartment_add_wifi_pass)
async def admin_apartment_add_wifi_pass(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Пароль Wi-Fi не может быть пустым.")
        return
    data = await state.get_data()
    apt = data.get("new_apartment", {})
    apt["wifi_pass"] = value
    await state.update_data(new_apartment=apt)
    await state.set_state(AdminState.waiting_apartment_add_checkin)
    await message.answer("Шаг 5/6: отправьте инструкцию по заселению.")


@router.message(AdminState.waiting_apartment_add_checkin)
async def admin_apartment_add_checkin(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Инструкция не может быть пустой.")
        return
    data = await state.get_data()
    apt = data.get("new_apartment", {})
    apt["check_in_instruction"] = value
    await state.update_data(new_apartment=apt)
    await state.set_state(AdminState.waiting_apartment_add_appliances)
    await message.answer("Шаг 6/6: отправьте инструкцию по бытовой технике.")


@router.message(AdminState.waiting_apartment_add_appliances)
async def admin_apartment_add_appliances(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Инструкция не может быть пустой.")
        return
    data = await state.get_data()
    apt = data.get("new_apartment", {})
    apt["appliances_guide"] = value
    apt["id"] = get_next_apartment_id()

    get_apartments().append(apt)
    save_content()

    back_idx = data.get("back_district_idx", 0)
    await state.clear()
    await message.answer(
        f"✅ Квартира добавлена: {escape_multiline(apt['address'])}.\n"
        f"Откройте /admin -> Квартиры -> нужный район (индекс {back_idx + 1})."
    )


@router.callback_query(F.data.startswith("adm:apt:s:"))
async def admin_apartment_select(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    apartment_id = int(callback.data.split(":")[3])
    apt = get_apartment(apartment_id)
    if apt is None:
        await callback.answer("Квартира не найдена", show_alert=True)
        return
    text = (
        "<b>Редактирование квартиры</b>\n\n"
        f"<b>ID:</b> {apt['id']}\n"
        f"<b>Район:</b> {escape_multiline(apt['district'])}\n"
        f"<b>Адрес:</b> {escape_multiline(apt['address'])}"
    )
    await safe_edit_text(callback, text, apartment_admin_card_kb(apartment_id))
    await callback.answer()


FIELD_MAP = {
    "ad": ("address", "Новый адрес"),
    "co": ("coords_link", "Новая ссылка на карту"),
    "wl": ("wifi_login", "Новый Wi-Fi логин"),
    "wp": ("wifi_pass", "Новый Wi-Fi пароль"),
    "ci": ("check_in_instruction", "Новая инструкция по заселению"),
    "ag": ("appliances_guide", "Новая инструкция по технике"),
}


@router.callback_query(F.data.startswith("adm:apt:f:"))
async def admin_apartment_field_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    parts = callback.data.split(":")
    field_code = parts[3]
    apartment_id = int(parts[4])
    apt = get_apartment(apartment_id)
    if apt is None or field_code not in FIELD_MAP:
        await callback.answer("Неверные данные", show_alert=True)
        return

    field_key, field_title = FIELD_MAP[field_code]
    await state.set_state(AdminState.waiting_apartment_edit_value)
    await state.update_data(edit_apartment_id=apartment_id, edit_field_key=field_key, edit_field_title=field_title)
    text = (
        "<b>Редактирование поля</b>\n\n"
        f"Квартира: {escape_multiline(apt['address'])}\n"
        f"Поле: {escape_multiline(field_title)}\n\n"
        "Отправьте новое значение одним сообщением."
    )
    await safe_edit_text(callback, text, prompt_back_kb(f"adm:apt:s:{apartment_id}"))
    await callback.answer()


@router.message(AdminState.waiting_apartment_edit_value)
async def admin_apartment_field_finish(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Значение не может быть пустым.")
        return

    data = await state.get_data()
    apartment_id = data.get("edit_apartment_id")
    field_key = data.get("edit_field_key")
    field_title = data.get("edit_field_title")
    apt = get_apartment(apartment_id)
    if apt is None or not field_key:
        await state.clear()
        await message.answer("Ошибка: квартира не найдена.")
        return

    apt[field_key] = value
    save_content()
    await state.clear()
    await message.answer(f"✅ Поле «{field_title}» обновлено.\nОткройте /admin для продолжения.")


@router.callback_query(F.data.startswith("adm:apt:mvsel:"))
async def admin_apartment_move_select(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    apartment_id = int(callback.data.split(":")[3])
    apt = get_apartment(apartment_id)
    if apt is None:
        await callback.answer("Квартира не найдена", show_alert=True)
        return
    text = (
        "<b>Переместить квартиру в другой район</b>\n\n"
        f"Квартира: {escape_multiline(apt['address'])}\n"
        f"Текущий район: {escape_multiline(apt['district'])}\n\n"
        "Выберите новый район:"
    )
    await safe_edit_text(callback, text, apartment_move_district_kb(apartment_id))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:apt:mv:"))
async def admin_apartment_move_finish(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    parts = callback.data.split(":")
    apartment_id = int(parts[3])
    district_idx = int(parts[4])
    apt = get_apartment(apartment_id)
    districts = get_districts()
    if apt is None or district_idx < 0 or district_idx >= len(districts):
        await callback.answer("Ошибка данных", show_alert=True)
        return
    apt["district"] = districts[district_idx]
    save_content()
    await safe_edit_text(callback, "✅ Квартира перемещена в другой район.", apartment_admin_card_kb(apartment_id))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:apt:del:"))
async def admin_apartment_delete(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    apartment_id = int(callback.data.split(":")[3])
    apartments = get_apartments()
    before_len = len(apartments)
    content["apartments"] = [a for a in apartments if int(a["id"]) != apartment_id]
    if len(content["apartments"]) == before_len:
        await callback.answer("Квартира не найдена", show_alert=True)
        return
    save_content()
    await safe_edit_text(callback, "✅ Квартира удалена.", apartments_admin_districts_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:faq")
async def admin_faq(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.clear()
    await safe_edit_text(callback, "<b>Управление FAQ</b>", faq_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:faq:add")
async def admin_faq_add_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.set_state(AdminState.waiting_faq_add_question)
    await safe_edit_text(
        callback,
        "<b>Новый FAQ</b>\n\nШаг 1/2: отправьте текст вопроса.",
        prompt_back_kb("adm:faq"),
    )
    await callback.answer()


@router.message(AdminState.waiting_faq_add_question)
async def admin_faq_add_question(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    question = (message.text or "").strip()
    if not question:
        await message.answer("Вопрос не может быть пустым.")
        return
    await state.update_data(new_faq_question=question)
    await state.set_state(AdminState.waiting_faq_add_answer)
    await message.answer("Шаг 2/2: отправьте текст ответа.")


@router.message(AdminState.waiting_faq_add_answer)
async def admin_faq_add_answer(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    answer = (message.text or "").strip()
    if not answer:
        await message.answer("Ответ не может быть пустым.")
        return
    data = await state.get_data()
    question = data.get("new_faq_question")
    get_faq_items().append({"question": question, "answer": answer})
    save_content()
    await state.clear()
    await message.answer("✅ FAQ добавлен. Откройте /admin для продолжения.")


@router.callback_query(F.data.startswith("adm:faq:s:"))
async def admin_faq_select(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    idx = int(callback.data.split(":")[3])
    faq_items = get_faq_items()
    if idx < 0 or idx >= len(faq_items):
        await callback.answer("Пункт FAQ не найден", show_alert=True)
        return
    item = faq_items[idx]
    text = (
        "<b>FAQ</b>\n\n"
        f"<b>Вопрос:</b> {escape_multiline(item['question'])}\n\n"
        f"<b>Ответ:</b> {escape_multiline(item['answer'])}"
    )
    await safe_edit_text(callback, text, faq_item_admin_kb(idx))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:faq:eq:"))
async def admin_faq_edit_question_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    idx = int(callback.data.split(":")[3])
    faq_items = get_faq_items()
    if idx < 0 or idx >= len(faq_items):
        await callback.answer("Пункт FAQ не найден", show_alert=True)
        return
    await state.set_state(AdminState.waiting_faq_edit_question)
    await state.update_data(edit_faq_idx=idx)
    await safe_edit_text(callback, "Отправьте новый текст вопроса.", prompt_back_kb(f"adm:faq:s:{idx}"))
    await callback.answer()


@router.message(AdminState.waiting_faq_edit_question)
async def admin_faq_edit_question_finish(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Текст не может быть пустым.")
        return
    data = await state.get_data()
    idx = data.get("edit_faq_idx")
    faq_items = get_faq_items()
    if idx is None or idx < 0 or idx >= len(faq_items):
        await state.clear()
        await message.answer("Ошибка: пункт FAQ не найден.")
        return
    faq_items[idx]["question"] = value
    save_content()
    await state.clear()
    await message.answer("✅ Вопрос FAQ обновлен. Откройте /admin.")


@router.callback_query(F.data.startswith("adm:faq:ea:"))
async def admin_faq_edit_answer_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    idx = int(callback.data.split(":")[3])
    faq_items = get_faq_items()
    if idx < 0 or idx >= len(faq_items):
        await callback.answer("Пункт FAQ не найден", show_alert=True)
        return
    await state.set_state(AdminState.waiting_faq_edit_answer)
    await state.update_data(edit_faq_idx=idx)
    await safe_edit_text(callback, "Отправьте новый текст ответа.", prompt_back_kb(f"adm:faq:s:{idx}"))
    await callback.answer()


@router.message(AdminState.waiting_faq_edit_answer)
async def admin_faq_edit_answer_finish(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Текст не может быть пустым.")
        return
    data = await state.get_data()
    idx = data.get("edit_faq_idx")
    faq_items = get_faq_items()
    if idx is None or idx < 0 or idx >= len(faq_items):
        await state.clear()
        await message.answer("Ошибка: пункт FAQ не найден.")
        return
    faq_items[idx]["answer"] = value
    save_content()
    await state.clear()
    await message.answer("✅ Ответ FAQ обновлен. Откройте /admin.")


@router.callback_query(F.data.startswith("adm:faq:del:"))
async def admin_faq_delete(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    idx = int(callback.data.split(":")[3])
    faq_items = get_faq_items()
    if idx < 0 or idx >= len(faq_items):
        await callback.answer("Пункт FAQ не найден", show_alert=True)
        return
    faq_items.pop(idx)
    save_content()
    await safe_edit_text(callback, "✅ Пункт FAQ удален.", faq_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:rules")
async def admin_rules(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.clear()
    text = f"<b>Текущий текст правил</b>\n\n{escape_multiline(get_rules_text())}"
    await safe_edit_text(callback, text, rules_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:rules:edit")
async def admin_rules_edit_start(callback: CallbackQuery, state: FSMContext):
    if not await require_editor(callback, state):
        return
    await state.set_state(AdminState.waiting_rules_text)
    text = "<b>Редактирование правил</b>\n\nОтправьте новый полный текст правил одним сообщением."
    await safe_edit_text(callback, text, prompt_back_kb("adm:rules"))
    await callback.answer()


@router.message(AdminState.waiting_rules_text)
async def admin_rules_edit_finish(message: Message, state: FSMContext):
    if not is_editor(message.from_user.id if message.from_user else 0):
        await state.clear()
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer("Текст правил не может быть пустым.")
        return
    content["rules"] = value
    save_content()
    await state.clear()
    await message.answer("✅ Правила обновлены. Откройте /admin.")


async def main():
    logging.basicConfig(level=logging.INFO)

    if config.bot_token == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise ValueError("Set bot_token in Config before running")

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    try:
        await bot.delete_webhook(drop_pending_updates=True, request_timeout=30)
    except TelegramNetworkError:
        logging.warning("Could not delete webhook due to network timeout. Continuing startup.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
