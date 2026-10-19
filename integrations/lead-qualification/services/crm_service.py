def get_crm_route(lead_score: int) -> str:
    if lead_score >= 80:
        return "Sales Team"
    if lead_score >= 50:
        return "SDR Queue"
    return "Nurture Campaign"
