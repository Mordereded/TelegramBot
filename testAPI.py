import requests


def decode_rank_tier(rank_tier):
    if not rank_tier:
        return "Нет данных"

    if rank_tier == 80:
        return "Immortal"

    medals = {
        1: "Herald",
        2: "Guardian",
        3: "Crusader",
        4: "Archon",
        5: "Legend",
        6: "Ancient",
        7: "Divine",
    }

    medal = medals.get(rank_tier // 10, "Unknown")
    star = rank_tier % 10
    return f"{medal} {star}"

def get_mmr_range_by_rank_tier(rank_tier: int) -> str:
    if not rank_tier:
        return "Нет данных"

    if rank_tier == 80:
        return "Immortal (Бессмертный) — от 5620 MMR"

    medal_names = {
        1: "Herald (Рекрут)",
        2: "Guardian (Страж)",
        3: "Crusader (Рыцарь)",
        4: "Archon (Герой)",
        5: "Legend (Легенда)",
        6: "Ancient (Властелин)",
        7: "Divine (Божество)"
    }

    medal = rank_tier // 10
    star = rank_tier % 10

    if medal not in medal_names or not (1 <= star <= 5):
        return "Неизвестный ранг"

    medal_base_mmr = (medal - 1) * 770
    star_step = 770 // 5  # 154 MMR
    mmr_min = medal_base_mmr + (star - 1) * star_step
    mmr_max = mmr_min + star_step - 1

    name = medal_names[medal]
    return f"{name} {star} ⭐ — {mmr_min}–{mmr_max} MMR"

steam_id = "370379348"
url = f"https://api.opendota.com/api/players/{steam_id}"

response = requests.get(url)
data = response.json()

mmr_estimate = data.get('mmr_estimate', {}).get('estimate')
rank_tier = data.get('rank_tier')
if(mmr_estimate == None):
    mmr_estimate = get_mmr_range_by_rank_tier(75)
print(f"Примерный MMR: {mmr_estimate}")
#print(f"Rank tier: {decode_rank_tier(rank_tier)}")