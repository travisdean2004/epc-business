import logging

logger = logging.getLogger(__name__)


def send_lead_notification(company: str, priority: str, lead_score: int, crm_route: str) -> None:
    message = (
        "\n[NOTIFICATION]\n"
        f"New {priority} Lead\n"
        f"Company: {company}\n"
        f"Score: {lead_score}\n"
        f"Route: {crm_route}\n"
    )
    logger.info(message)
    print(message)
