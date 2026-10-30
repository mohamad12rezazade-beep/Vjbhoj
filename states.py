from aiogram.fsm.state import State, StatesGroup

class CreateLottery(StatesGroup):
    winners_count = State()
    prizes = State()
    min_participants = State()
    max_participants = State()
    duration = State()
    mode = State()
    required_channels = State()
    publish_channel = State()
    post_text = State()
    preview = State()
