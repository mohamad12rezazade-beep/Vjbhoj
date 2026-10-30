from aiogram.fsm.state import State, StatesGroup


class CreateGiveaway(StatesGroup):

    # تعداد برندگان
    winner_count = State()

    # جایزه هر رتبه
    prizes = State()

    # حداقل شرکت‌کنندگان
    min_users = State()

    # حداکثر شرکت‌کنندگان
    max_users = State()

    # مدت قرعه‌کشی به ساعت
    duration = State()

    # روش انتخاب برنده
    mode = State()

    # کانال‌های جوین اجباری
    required_channels = State()

    # کانال انتشار قرعه‌کشی
    target_channel = State()

    # متن دلخواه پست
    post_text = State()
